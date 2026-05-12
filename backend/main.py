"""
Law Minister's Office — AI-Powered Staff Attendance System

FastAPI backend serving both the REST API and the web dashboard.
Run: python -m backend.main
"""

import asyncio
import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend import database as db
from backend.attendance import engine as attendance_engine
from backend import face_engine
from backend import whatsapp as wa
from backend.config import load_config, save_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("attendance.main")

STATIC_DIR = Path(__file__).parent.parent / "frontend"
FACE_IMAGES_DIR = Path(__file__).parent.parent / "face_images"
FACE_IMAGES_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Staff Attendance System started")
    yield
    attendance_engine.stop()
    logger.info("Staff Attendance System stopped")


app = FastAPI(
    title="Law Minister's Office — Staff Attendance System",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/face_images", StaticFiles(directory=str(FACE_IMAGES_DIR)), name="face_images")


# ---- Dashboard ----

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Frontend not found</h1>")


# ---- Staff Management ----

@app.get("/api/staff")
async def list_staff():
    staff = db.get_all_staff(active_only=False)
    for s in staff:
        encodings = db.get_face_encodings(s["staff_id"])
        s["face_count"] = len(encodings)
    return {"staff": staff}


@app.post("/api/staff")
async def create_staff(
    staff_id: str = Form(...),
    name: str = Form(...),
    designation: str = Form(""),
    department: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
):
    existing = db.get_staff(staff_id)
    if existing:
        raise HTTPException(400, f"Staff ID {staff_id} already exists")
    db.add_staff(staff_id, name, designation, department, phone, email)
    return {"success": True, "staff_id": staff_id}


@app.put("/api/staff/{staff_id}")
async def update_staff(staff_id: str, request: Request):
    data = await request.json()
    if not db.get_staff(staff_id):
        raise HTTPException(404, "Staff not found")
    db.update_staff(staff_id, **data)
    return {"success": True}


@app.delete("/api/staff/{staff_id}")
async def delete_staff(staff_id: str):
    if not db.delete_staff(staff_id):
        raise HTTPException(404, "Staff not found")
    return {"success": True}


# ---- Face Registration ----

@app.post("/api/staff/{staff_id}/face")
async def register_face(
    staff_id: str,
    photo: UploadFile = File(...),
    angle: str = Form("front"),
):
    staff = db.get_staff(staff_id)
    if not staff:
        raise HTTPException(404, "Staff not found")

    image_bytes = await photo.read()
    result = face_engine.register_staff_face(staff_id, image_bytes, angle)

    if not result["success"]:
        raise HTTPException(400, result["error"])

    return result


@app.get("/api/staff/{staff_id}/faces")
async def get_staff_faces(staff_id: str):
    encodings = db.get_face_encodings(staff_id)
    faces = []
    for enc in encodings:
        faces.append({
            "id": enc["id"],
            "angle": enc["angle"],
            "image_path": enc["image_path"],
            "created_at": enc["created_at"],
        })
    return {"faces": faces}


@app.delete("/api/staff/{staff_id}/faces")
async def delete_staff_faces(staff_id: str):
    db.delete_face_encodings(staff_id)
    return {"success": True}


# ---- Attendance ----

@app.get("/api/attendance")
async def get_attendance(date: str = None):
    records = db.get_attendance(date)
    return {"attendance": records, "count": len(records)}


@app.get("/api/attendance/summary")
async def get_summary(date: str = None):
    summary = db.get_attendance_summary(date)
    return summary


@app.get("/api/attendance/range")
async def get_attendance_range(start: str = None, end: str = None):
    if not start or not end:
        raise HTTPException(400, "start and end dates required")
    records = db.get_attendance_range(start, end)
    return {"attendance": records, "count": len(records)}


@app.get("/api/attendance/report")
async def attendance_report(date: str = None):
    """Generate attendance report for export."""
    records = db.get_attendance(date)
    all_staff = db.get_all_staff()
    present_ids = {r["staff_id"] for r in records}

    report = []
    for staff in all_staff:
        sid = staff["staff_id"]
        record = next((r for r in records if r["staff_id"] == sid), None)
        report.append({
            "staff_id": sid,
            "name": staff["name"],
            "designation": staff["designation"],
            "department": staff["department"],
            "status": "Present" if sid in present_ids else "Absent",
            "time_in": record["logged_at"] if record else "",
            "confidence": record["confidence"] if record else 0,
        })

    return {"report": report, "date": date or str(datetime.now().date())}


@app.post("/api/attendance/manual-checkin")
async def manual_checkin(photo: UploadFile = File(...)):
    """Process a single photo for attendance (manual/test mode)."""
    image_bytes = await photo.read()
    records = attendance_engine.process_single_image(image_bytes)
    return {"records": records}


# ---- Attendance Engine Control ----

@app.post("/api/engine/start")
async def start_engine():
    attendance_engine.start()
    return {"success": True, "status": "running"}


@app.post("/api/engine/stop")
async def stop_engine():
    attendance_engine.stop()
    return {"success": True, "status": "stopped"}


@app.get("/api/engine/status")
async def engine_status():
    return attendance_engine.stats


# ---- Camera Management ----

@app.get("/api/cameras")
async def list_cameras():
    cameras = db.get_cameras(active_only=False)
    safe_cameras = []
    for c in cameras:
        c_dict = dict(c)
        c_dict["password"] = "***" if c_dict.get("password") else ""
        safe_cameras.append(c_dict)
    return {"cameras": safe_cameras}


@app.post("/api/cameras")
async def add_camera(request: Request):
    data = await request.json()
    cam_id = db.add_camera(
        name=data.get("name", "Camera"),
        source_type=data.get("source_type", "rtsp"),
        source_url=data.get("source_url", ""),
        ip=data.get("ip", ""),
        port=data.get("port", 554),
        username=data.get("username", ""),
        password=data.get("password", ""),
        channel=data.get("channel", 1),
        description=data.get("description", ""),
    )
    return {"success": True, "id": cam_id}


@app.put("/api/cameras/{camera_id}")
async def update_camera(camera_id: int, request: Request):
    data = await request.json()
    db.update_camera(camera_id, **data)
    return {"success": True}


@app.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: int):
    if not db.delete_camera(camera_id):
        raise HTTPException(404, "Camera not found")
    return {"success": True}


@app.post("/api/cameras/{camera_id}/test")
async def test_camera(camera_id: int):
    """Test camera connection by capturing a frame."""
    cameras = db.get_cameras(active_only=False)
    cam_cfg = next((c for c in cameras if c["id"] == camera_id), None)
    if not cam_cfg:
        raise HTTPException(404, "Camera not found")

    from backend.camera import capture_from_camera
    frame = capture_from_camera(cam_cfg)
    if frame is None:
        return {"success": False, "error": "Failed to capture frame"}

    return {"success": True, "frame_size": len(frame)}


# ---- Settings ----

@app.get("/api/settings")
async def get_settings():
    cfg = load_config()
    return cfg


@app.put("/api/settings")
async def update_settings(request: Request):
    data = await request.json()
    cfg = load_config()
    cfg.update(data)
    save_config(cfg)
    return {"success": True}


@app.post("/api/whatsapp/test")
async def test_whatsapp(request: Request):
    """Send a test WhatsApp message to verify configuration."""
    data = await request.json()
    recipient = data.get("recipient", "")
    if not recipient:
        raise HTTPException(400, "Recipient number required")
    cfg = load_config()
    cfg["whatsapp_enabled"] = True
    cfg["whatsapp_recipient"] = recipient
    body = (
        "Office Attendance System — Test Message\n\n"
        "WhatsApp notifications are configured and working.\n"
        "Attendance alerts will be sent to this number.\n\n"
        "Office of Shri Arjun Ram Meghwal Ji\n"
        "Honourable Law Minister\n"
        "— LEGIT COMMUNISYS"
    )
    ok = wa.send_text_message(cfg, recipient, body)
    return {"success": ok}


@app.post("/api/whatsapp/welcome")
async def send_welcome(request: Request):
    """Send the face registration welcome message to a staff member."""
    data = await request.json()
    recipient = data.get("recipient", "")
    if not recipient:
        raise HTTPException(400, "Recipient number required")
    cfg = load_config()
    ok = wa.send_welcome_message(cfg, recipient)
    return {"success": ok}


@app.post("/api/whatsapp/template")
async def send_template(request: Request):
    """Send a pre-approved template message (bypasses 24h opt-in)."""
    data = await request.json()
    recipient = data.get("recipient", "")
    template_name = data.get("template", "")
    parameters = data.get("parameters", [])
    if not recipient or not template_name:
        raise HTTPException(400, "recipient and template required")
    cfg = load_config()
    ok = wa.send_template_message(cfg, recipient, template_name, parameters)
    return {"success": ok}


# ---- WhatsApp Webhook (incoming messages) ----

@app.get("/api/whatsapp/webhook")
async def webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification (GET request).

    Meta sends a GET with hub.mode, hub.verify_token, and hub.challenge.
    We must return the challenge value if the token matches.
    """
    if not hub_mode or not hub_verify_token or not hub_challenge:
        raise HTTPException(400, "Missing verification parameters")

    challenge = wa.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is not None:
        return PlainTextResponse(content=challenge)
    raise HTTPException(403, "Verification failed")


@app.post("/api/whatsapp/webhook")
async def webhook_receive(request: Request):
    """Receive incoming WhatsApp messages from Meta webhook.

    Auto-responds to greetings and unrelated messages per bot rules.
    Supports Hindi, English, and Hinglish language detection.
    """
    payload = await request.json()
    logger.info(f"Webhook received: {payload.get('object', 'unknown')}")

    cfg = load_config()
    actions = wa.handle_incoming_webhook(cfg, payload)

    return JSONResponse(content={"status": "ok", "actions": actions})


# ---- Export ----

@app.get("/api/export/attendance")
async def export_attendance(date: str = None, format: str = "csv"):
    """Export attendance data as CSV."""
    records = db.get_attendance(date)
    all_staff = db.get_all_staff()
    present_ids = {r["staff_id"] for r in records}

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Staff ID", "Name", "Designation", "Department",
                         "Status", "Time In", "Confidence"])
        for staff in all_staff:
            sid = staff["staff_id"]
            record = next((r for r in records if r["staff_id"] == sid), None)
            status = "Present" if sid in present_ids else "Absent"
            time_in = record["logged_at"] if record else ""
            conf = f"{record['confidence']:.3f}" if record else ""
            writer.writerow([sid, staff["name"], staff["designation"],
                             staff["department"], status, time_in, conf])
        csv_content = output.getvalue()
        return JSONResponse(
            content={"csv": csv_content, "filename": f"attendance_{date or 'today'}.csv"}
        )

    raise HTTPException(400, "Unsupported format")


def run():
    import uvicorn
    cfg = load_config()
    port = cfg.get("local_port", 8900)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run()
