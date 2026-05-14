"""
Law Minister WhatsApp Bot — Standalone Cloud Backend

This is an independent FastAPI service for the Law Minister's Office
WhatsApp Bot. It handles:
- WhatsApp webhook verification and message routing
- Auto-responses (greeting, unrelated, office-topic)
- Admin commands (summary, staff, today, etc.)
- Message logging
- Attendance notification API (called by the face recognition engine)
- Periodic webhook re-registration

Deployment: Fly.io as 'law-minister-bot' (separate from PPIS)
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from bot_service.config import (
    WEBHOOK_VERIFY_TOKEN, LAW_MINISTER_PHONE_ID, HOST, PORT, ADMINS,
)
from bot_service import database as db
from bot_service import whatsapp as wa
from bot_service.bot_handler import handle_webhook
from bot_service.reports import generate_summary_excel, generate_attendance_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lm_bot.main")


# ---------- Scheduler ----------

def _setup_scheduler():
    """Set up periodic tasks."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    async def _keep_alive():
        result = await wa.ensure_webhook_registration()
        logger.info(f"Keep-alive registration: {result}")

    scheduler.add_job(_keep_alive, "interval", hours=2, id="lm_keep_alive")
    scheduler.start()
    logger.info("Scheduler started: webhook keep-alive every 2 hours")
    return scheduler


# ---------- Lifespan ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    logger.info("Database initialized")

    # Register webhook on startup
    result = await wa.ensure_webhook_registration()
    logger.info(f"Startup registration: {result}")

    # Start scheduler
    scheduler = _setup_scheduler()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Bot service shutting down")


# ---------- App ----------

app = FastAPI(
    title="Law Minister WhatsApp Bot",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------- Health ----------

@app.get("/")
async def root():
    return {"status": "ok", "service": "law-minister-bot", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ---------- Webhook ----------

@app.get("/webhook")
async def webhook_verify(request: Request):
    """Meta webhook verification (GET)."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(content=challenge)

    logger.warning(f"Webhook verification failed: mode={mode}, token={token}")
    return JSONResponse(status_code=403, content={"error": "Verification failed"})


@app.post("/webhook")
async def webhook_receive(request: Request):
    """Process incoming WhatsApp webhook (POST)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    # Process asynchronously
    result = await handle_webhook(body)
    return JSONResponse(content=result)


# ---------- API Endpoints ----------

@app.post("/api/notify-attendance")
async def notify_attendance(request: Request):
    """Called by the face recognition engine when attendance is marked.

    Expected JSON:
    {
        "staff_name": "Rahul Sharma",
        "phone": "9876543210",
        "date": "07/05/2026",
        "time": "09:30 AM",
        "snapshot_path": "/path/to/snapshot.jpg"  (optional)
    }
    """
    data = await request.json()
    staff_name = data.get("staff_name", "")
    phone = data.get("phone", "")
    date_str = data.get("date", "")
    time_str = data.get("time", "")
    snapshot_path = data.get("snapshot_path", "")

    if not staff_name or not phone:
        return JSONResponse(status_code=400, content={"error": "staff_name and phone required"})

    # Try template message with image
    template_name = "law_minister_attendance_notification"
    parameters = [staff_name, date_str, time_str]

    sent = False
    if snapshot_path and os.path.exists(snapshot_path):
        # Upload image and send template with header
        media_id = None
        try:
            token = wa._get_token()
            if token:
                import httpx
                headers = {"Authorization": f"Bearer {token}"}
                upload_url = f"https://graph.facebook.com/v21.0/{LAW_MINISTER_PHONE_ID}/media"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    with open(snapshot_path, "rb") as f:
                        resp = await client.post(
                            upload_url,
                            headers=headers,
                            data={"messaging_product": "whatsapp", "type": "image/jpeg"},
                            files={"file": (os.path.basename(snapshot_path), f, "image/jpeg")},
                        )
                    if resp.status_code == 200:
                        media_id = resp.json().get("id")
        except Exception as e:
            logger.error(f"Snapshot upload failed: {e}")

        if media_id:
            sent = await wa.send_template(phone, template_name, parameters, header_media_id=media_id)

    # Fallback: template without image
    if not sent:
        sent = await wa.send_template(phone, template_name, parameters)

    # Fallback: image + caption
    if not sent and snapshot_path and os.path.exists(snapshot_path):
        caption = f"✅ Attendance Marked\n\nName: {staff_name}\nDate: {date_str}\nTime: {time_str}\nStatus: Present"
        sent = await wa.send_image(phone, snapshot_path, caption)

    # Final fallback: text only
    if not sent:
        text = f"✅ Attendance Marked\n\nName: {staff_name}\nDate: {date_str}\nTime: {time_str}\nStatus: Present"
        sent = await wa.send_text(phone, text)

    # Log the notification
    await db.log_message(
        direction="outgoing",
        sender=LAW_MINISTER_PHONE_ID,
        recipient=phone,
        content=f"Attendance notification: {staff_name} at {time_str}",
        category="attendance_notification",
    )

    return JSONResponse(content={"sent": sent, "staff": staff_name})


@app.get("/api/messages")
async def get_messages(days: int = Query(default=7, ge=1, le=90)):
    """Get message log (for desktop admin panel)."""
    messages = await db.get_messages(days=days)
    return JSONResponse(content={"messages": messages, "count": len(messages)})


@app.get("/api/staff")
async def get_staff():
    """Get staff list (for desktop admin panel)."""
    staff = await db.get_staff_list()
    return JSONResponse(content={"staff": staff})


@app.post("/api/staff")
async def add_staff(request: Request):
    """Add a staff member."""
    data = await request.json()
    name = data.get("name", "")
    phone = data.get("phone", "")
    designation = data.get("designation", "")
    if not name or not phone:
        return JSONResponse(status_code=400, content={"error": "name and phone required"})
    success = await db.add_staff(name, phone, designation)
    return JSONResponse(content={"success": success})


@app.get("/api/attendance")
async def get_attendance(date: str = Query(default="")):
    """Get attendance records (for desktop admin panel)."""
    records = await db.get_attendance_records(date)
    return JSONResponse(content={"records": records, "count": len(records)})


@app.get("/api/report/messages")
async def download_message_report(days: int = Query(default=7, ge=1, le=90)):
    """Download message report as Excel."""
    filepath = await generate_summary_excel(days=days)
    if not filepath:
        return JSONResponse(status_code=404, content={"error": "No data"})
    from fastapi.responses import FileResponse
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="message_summary.xlsx",
    )


@app.get("/api/report/attendance")
async def download_attendance_report(date: str = Query(default="")):
    """Download attendance report as Excel."""
    filepath = await generate_attendance_excel(date)
    if not filepath:
        return JSONResponse(status_code=404, content={"error": "No data"})
    from fastapi.responses import FileResponse
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="attendance_report.xlsx",
    )


# ---------- Run ----------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot_service.main:app", host=HOST, port=PORT, reload=True)
