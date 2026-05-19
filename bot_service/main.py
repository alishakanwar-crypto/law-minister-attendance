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
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from bot_service.config import (
    WEBHOOK_VERIFY_TOKEN, LAW_MINISTER_PHONE_ID, HOST, PORT, ADMINS,
)
from bot_service import database as db
from bot_service import whatsapp as wa
from bot_service import ist_time
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


# ---------- Static / Dashboard ----------

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the web-based command centre."""
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text())


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------- Health ----------

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "law-minister-bot",
        "version": "2.1.0",
        "timestamp_ist": ist_time.now_human(),
        "timezone": "Asia/Kolkata (IST, UTC+5:30)",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp_ist": ist_time.now_human(),
        "iso": ist_time.now_iso(),
    }


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
        "date": "07/05/2026",  (optional — defaults to current IST date)
        "time": "09:30 AM IST" (optional — defaults to current IST time)
    }
    """
    data = await request.json()
    staff_name = data.get("staff_name", "")
    phone = data.get("phone", "")

    # Always use IST — override or default
    ts = ist_time.now_timestamp_full()
    date_str = data.get("date", "") or ts["date"]
    time_str = data.get("time", "") or ts["time_12h"]

    if not staff_name or not phone:
        return JSONResponse(status_code=400, content={"error": "staff_name and phone required"})

    # Send text-only template (no image header)
    template_name = "law_minister_attendance"
    parameters = [staff_name, date_str, time_str]

    sent = await wa.send_template(phone, template_name, parameters)

    # Fallback: plain text if template fails
    if not sent:
        text = (
            f"Attendance Marked Successfully\n\n"
            f"Name: {staff_name}\n"
            f"Date: {date_str}\n"
            f"Time: {time_str}\n"
            f"Status: Present\n\n"
            f"Timestamp: {ts['human']}"
        )
        sent = await wa.send_text(phone, text)

    # Log the notification with IST timestamp
    await db.log_message(
        direction="outgoing",
        sender=LAW_MINISTER_PHONE_ID,
        recipient=phone,
        content=f"Attendance notification: {staff_name} at {time_str} on {date_str}",
        category="attendance_notification",
    )

    return JSONResponse(content={
        "sent": sent,
        "staff": staff_name,
        "timestamp_ist": ts["human"],
        "iso": ts["iso"],
    })


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


def _cleanup_file(path: str):
    try:
        os.unlink(path)
    except Exception:
        pass


@app.get("/api/report/messages")
async def download_message_report(days: int = Query(default=7, ge=1, le=90)):
    """Download message report as Excel."""
    filepath = await generate_summary_excel(days=days)
    if not filepath:
        return JSONResponse(status_code=404, content={"error": "No data"})
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="message_summary.xlsx",
        background=BackgroundTask(_cleanup_file, filepath),
    )


@app.get("/api/report/attendance")
async def download_attendance_report(date: str = Query(default="")):
    """Download attendance report as Excel."""
    filepath = await generate_attendance_excel(date)
    if not filepath:
        return JSONResponse(status_code=404, content={"error": "No data"})
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="attendance_report.xlsx",
        background=BackgroundTask(_cleanup_file, filepath),
    )


# ---------- Face Registration API ----------

@app.get("/api/registrations")
async def get_registrations(status: str = Query(default="")):
    """Get face registration records."""
    registrations = await db.get_all_registrations(status)
    return JSONResponse(content={"registrations": registrations, "count": len(registrations)})


@app.get("/api/registrations/stats")
async def get_registration_stats():
    """Get face registration statistics."""
    stats = await db.get_registration_stats()
    return JSONResponse(content=stats)


@app.get("/api/registrations/pending-sync")
async def get_pending_sync():
    """Get registrations that need to be synced to the face engine."""
    pending = await db.get_pending_sync_registrations()
    return JSONResponse(content={"pending": pending, "count": len(pending)})


@app.post("/api/registrations/mark-synced")
async def mark_synced(request: Request):
    """Mark a registration as synced to the face recognition engine."""
    data = await request.json()
    reg_id = data.get("id")
    if not reg_id:
        return JSONResponse(status_code=400, content={"error": "id required"})
    success = await db.mark_registration_synced(reg_id)
    return JSONResponse(content={"success": success})


@app.get("/api/registrations/image/{reg_id}")
async def download_registration_image(reg_id: int):
    """Download the face image for a registration (used by office PC sync)."""
    reg = await db.get_registration_by_id(reg_id)
    if not reg:
        return JSONResponse(status_code=404, content={"error": "Registration not found"})

    image_path = reg.get("image_path", "")
    if not image_path or not Path(image_path).exists():
        return JSONResponse(status_code=404, content={"error": "Image file not found"})

    # Validate the path is within the expected face images directory
    from bot_service.face_registration import FACE_IMAGES_DIR
    try:
        resolved = Path(image_path).resolve()
        if not str(resolved).startswith(str(FACE_IMAGES_DIR.resolve())):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
    except Exception:
        return JSONResponse(status_code=403, content={"error": "Invalid path"})

    from fastapi.responses import FileResponse
    return FileResponse(
        image_path,
        media_type="image/jpeg",
        filename=Path(image_path).name,
    )


# ---------- Remote Engine Logs ----------

_engine_log_buffer: deque[str] = deque(maxlen=500)


@app.post("/api/engine-logs")
async def receive_engine_logs(request: Request):
    """Receive log lines pushed by the office engine."""
    data = await request.json()
    lines = data.get("lines", [])
    for line in lines:
        _engine_log_buffer.append(line)
    return JSONResponse(content={"received": len(lines), "total": len(_engine_log_buffer)})


@app.get("/api/engine-logs")
async def get_engine_logs(limit: int = Query(default=200, ge=1, le=500)):
    """Get recent engine log lines."""
    logs = list(_engine_log_buffer)
    return JSONResponse(content={"logs": logs[-limit:], "count": len(logs)})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page():
    """Serve a simple log viewer page."""
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Engine Logs — Law Minister Attendance</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }
        h1 { color: #00d4ff; font-size: 18px; margin-bottom: 10px; }
        .controls { margin-bottom: 10px; }
        .controls button { background: #00d4ff; color: #1a1a2e; border: none; padding: 8px 16px; cursor: pointer; border-radius: 4px; font-weight: bold; margin-right: 8px; }
        .controls button:hover { background: #00b8d9; }
        .controls label { margin-left: 16px; color: #aaa; }
        #status { color: #aaa; font-size: 12px; margin-bottom: 8px; }
        #log-container { background: #0d0d1a; border: 1px solid #333; border-radius: 4px; padding: 12px; height: 70vh; overflow-y: auto; white-space: pre-wrap; word-break: break-all; font-size: 13px; line-height: 1.5; }
        .log-line { padding: 1px 0; }
        .log-line.error { color: #ff6b6b; }
        .log-line.warning { color: #ffd93d; }
        .log-line.attendance { color: #6bff6b; font-weight: bold; }
        .log-line.info { color: #e0e0e0; }
    </style>
</head>
<body>
    <h1>Office Engine Logs (Live)</h1>
    <div class="controls">
        <button onclick="fetchLogs()">Refresh Now</button>
        <label><input type="checkbox" id="autoRefresh" checked> Auto-refresh (10s)</label>
    </div>
    <div id="status">Loading...</div>
    <div id="log-container"></div>
    <script>
        const container = document.getElementById('log-container');
        const status = document.getElementById('status');
        let autoScroll = true;
        container.addEventListener('scroll', () => {
            autoScroll = container.scrollTop + container.clientHeight >= container.scrollHeight - 50;
        });
        function classifyLine(line) {
            if (line.includes('ERROR')) return 'error';
            if (line.includes('WARNING')) return 'warning';
            if (line.includes('ATTENDANCE:')) return 'attendance';
            return 'info';
        }
        async function fetchLogs() {
            try {
                const resp = await fetch('/api/engine-logs?limit=500');
                const data = await resp.json();
                container.innerHTML = data.logs.map(l => `<div class="log-line ${classifyLine(l)}">${l.replace(/</g,'&lt;')}</div>`).join('');
                status.textContent = `${data.count} log lines — last updated: ${new Date().toLocaleTimeString()}`;
                if (autoScroll) container.scrollTop = container.scrollHeight;
            } catch(e) {
                status.textContent = 'Error fetching logs: ' + e.message;
            }
        }
        fetchLogs();
        setInterval(() => { if (document.getElementById('autoRefresh').checked) fetchLogs(); }, 10000);
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/api/registrations/reset-sync")
async def reset_sync():
    """Reset all registration sync flags so the office engine re-processes them."""
    conn = await db.get_db()
    try:
        await conn.execute("UPDATE face_registrations SET embedding_synced = 0 WHERE status = 'registered'")
        await conn.commit()
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM face_registrations WHERE status = 'registered' AND embedding_synced = 0")
        row = await cursor.fetchone()
        count = row["cnt"] if row else 0
        return JSONResponse(content={"reset": True, "pending_count": count})
    finally:
        await conn.close()


# ---------- Run ----------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot_service.main:app", host=HOST, port=PORT, reload=True)
