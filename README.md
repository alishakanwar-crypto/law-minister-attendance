# Law Minister's Office — AI-Powered Staff Attendance System

Face recognition-based staff attendance system using InsightFace (512-dimensional ArcFace embeddings). Runs on your PC and connects to IP cameras at the office.

## Features

- **Face Recognition Attendance** — automated check-in via camera feeds (Hikvision, RTSP, webcam)
- **Staff Enrollment** — register staff with photo upload, multiple angles
- **Real-time Dashboard** — live attendance status, present/absent counts
- **Flexible Camera Support** — Hikvision ISAPI, RTSP streams, USB webcam, or image URLs
- **Attendance Reports** — daily reports with CSV export
- **Manual Check-in** — test mode with photo upload
- **Configurable** — attendance window, recognition threshold, cooldown period

## Architecture

```
Camera (at Minister's Office)
    ↓ RTSP / ISAPI over network
Your PC (runs this software)
    ├── Face Recognition Engine (InsightFace buffalo_l)
    ├── SQLite Database (staff, attendance, cameras)
    └── Web Dashboard (http://localhost:8900)
```

## Quick Start

### Option A: Standalone Desktop App (Recommended)

```bash
# Python 3.10+ required
pip install -r requirements.txt
python desktop_app.py
```

The desktop app opens with a full GUI — no browser needed. Everything runs in one window.

### Option B: Web Dashboard

```bash
pip install -r requirements.txt
python -m backend.main
```

Open **http://localhost:8900** in your browser.

### Option C: Build Windows .exe

```bash
pip install -r requirements.txt
python build_exe.py
```

This creates `dist/LawMinisterAttendance/LawMinisterAttendance.exe` — double-click to run.

### Setup Steps

1. **Add Staff** — Go to Staff tab → Add Staff (with face photo)
2. **Add Camera** — Go to Cameras tab → Add Camera (enter IP/RTSP details)
3. **Configure** — Go to Settings tab → Set attendance window, threshold
4. **Start Engine** — Click "▶ Start" in the header to begin monitoring

## Camera Setup

### Hikvision DVR/NVR
- Type: `Hikvision ISAPI`
- IP: Camera/DVR IP address
- Port: 80 (HTTP)
- Username/Password: DVR credentials
- Channel: Camera channel number

### RTSP (Any IP Camera)
- Type: `RTSP Stream`
- URL: `rtsp://username:password@ip:554/Streaming/channels/101`

### USB Webcam (Testing)
- Type: `USB Webcam`
- Device Index: 0 (default camera)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/staff` | List all staff |
| POST | `/api/staff` | Add new staff |
| POST | `/api/staff/{id}/face` | Register face photo |
| GET | `/api/attendance` | Today's attendance |
| GET | `/api/attendance/summary` | Summary stats |
| GET | `/api/attendance/report` | Full report |
| POST | `/api/attendance/manual-checkin` | Manual photo check-in |
| POST | `/api/engine/start` | Start monitoring |
| POST | `/api/engine/stop` | Stop monitoring |
| GET | `/api/cameras` | List cameras |
| POST | `/api/cameras` | Add camera |
| GET | `/api/export/attendance` | Export CSV |

## Configuration

Settings can be changed via the dashboard or `config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `office_name` | Law Minister's Office | Display name |
| `attendance_start_hour` | 9 | Start of attendance window |
| `attendance_end_hour` | 11 | End of attendance window |
| `recognition_threshold` | 0.45 | Minimum match confidence (0-1) |
| `cooldown_seconds` | 300 | Seconds between re-logging same person |
| `snapshot_interval_seconds` | 5 | Seconds between camera captures |

## Technology

- **InsightFace buffalo_l** — 512-dimensional ArcFace facial embeddings
- **CustomTkinter** — modern desktop GUI framework
- **FastAPI** — async Python web framework (web dashboard mode)
- **SQLite** — local database (WAL mode)
- **OpenCV** — camera frame capture
- **Pillow** — image preprocessing
- **PyInstaller** — Windows .exe packaging

## Project by

**LEGIT COMMUNISYS CONSULTING PRIVATE LIMITED**
Unit No. 111, Aggarwal City Square, Plot No. 10, District Centre,
Manglam Place, Sector-3, Rohini, Delhi, India, 110085
