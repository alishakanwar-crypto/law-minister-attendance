"""
SQLite database for staff attendance system.

Tables:
- staff: registered staff members with face encodings
- attendance_log: timestamped attendance records
- cameras: configured camera sources
- settings: key-value configuration
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("attendance.db")

DB_PATH = Path(__file__).parent.parent / "attendance.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS staff (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id        TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                designation     TEXT NOT NULL DEFAULT '',
                department      TEXT NOT NULL DEFAULT '',
                phone           TEXT NOT NULL DEFAULT '',
                email           TEXT NOT NULL DEFAULT '',
                active          INTEGER NOT NULL DEFAULT 1,
                registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS face_encodings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id        TEXT NOT NULL,
                angle           TEXT NOT NULL DEFAULT 'front',
                encoding        BLOB NOT NULL,
                encoding_type   TEXT NOT NULL DEFAULT 'insightface_512d',
                image_path      TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (staff_id) REFERENCES staff(staff_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS attendance_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id        TEXT NOT NULL,
                name            TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'Present',
                confidence      REAL NOT NULL DEFAULT 0.0,
                snapshot_path   TEXT NOT NULL DEFAULT '',
                camera_source   TEXT NOT NULL DEFAULT '',
                logged_at       TEXT NOT NULL DEFAULT (datetime('now')),
                date            TEXT NOT NULL DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS cameras (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                source_type     TEXT NOT NULL DEFAULT 'rtsp',
                source_url      TEXT NOT NULL DEFAULT '',
                ip              TEXT NOT NULL DEFAULT '',
                port            INTEGER NOT NULL DEFAULT 554,
                username        TEXT NOT NULL DEFAULT '',
                password        TEXT NOT NULL DEFAULT '',
                channel         INTEGER NOT NULL DEFAULT 1,
                active          INTEGER NOT NULL DEFAULT 1,
                description     TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS settings (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_attendance_date
                ON attendance_log(date);
            CREATE INDEX IF NOT EXISTS idx_attendance_staff
                ON attendance_log(staff_id, date);
            CREATE INDEX IF NOT EXISTS idx_face_staff
                ON face_encodings(staff_id);
        """)
        conn.commit()
        logger.info(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()


# --- Staff CRUD ---

def add_staff(staff_id: str, name: str, designation: str = "",
              department: str = "", phone: str = "", email: str = "") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO staff (staff_id, name, designation, department, phone, email) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (staff_id, name, designation, department, phone, email),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_staff(staff_id: str, **kwargs) -> bool:
    allowed = {"name", "designation", "department", "phone", "email", "active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = ?" if k != "updated_at" else f"{k} = datetime('now')"
        for k in fields
    )
    values = [v for k, v in fields.items() if k != "updated_at"]
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE staff SET {set_clause} WHERE staff_id = ?",
            (*values, staff_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_staff(staff_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM staff WHERE staff_id = ?", (staff_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_staff(active_only: bool = True) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM staff"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY name"
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_staff(staff_id: str) -> bool:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM face_encodings WHERE staff_id = ?", (staff_id,))
        cur = conn.execute("DELETE FROM staff WHERE staff_id = ?", (staff_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# --- Face Encodings ---

def save_face_encoding(staff_id: str, angle: str, encoding_bytes: bytes,
                       image_path: str = "",
                       encoding_type: str = "insightface_512d") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO face_encodings (staff_id, angle, encoding, encoding_type, image_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (staff_id, angle, encoding_bytes, encoding_type, image_path),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_face_encodings(staff_id: str = None,
                       encoding_type: str = "insightface_512d") -> list[dict]:
    conn = get_conn()
    try:
        if staff_id:
            rows = conn.execute(
                "SELECT fe.*, s.name, s.designation FROM face_encodings fe "
                "JOIN staff s ON fe.staff_id = s.staff_id "
                "WHERE fe.staff_id = ? AND fe.encoding_type = ? AND s.active = 1",
                (staff_id, encoding_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT fe.*, s.name, s.designation FROM face_encodings fe "
                "JOIN staff s ON fe.staff_id = s.staff_id "
                "WHERE fe.encoding_type = ? AND s.active = 1",
                (encoding_type,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_face_encodings(staff_id: str):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM face_encodings WHERE staff_id = ?", (staff_id,))
        conn.commit()
    finally:
        conn.close()


# --- Attendance ---

def log_attendance(staff_id: str, name: str, confidence: float,
                   snapshot_path: str = "", camera_source: str = "",
                   date_str: str = None) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO attendance_log (staff_id, name, confidence, snapshot_path, "
            "camera_source, date) VALUES (?, ?, ?, ?, ?, COALESCE(?, date('now')))",
            (staff_id, name, confidence, snapshot_path, camera_source, date_str),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_attendance(date_str: str = None) -> list[dict]:
    conn = get_conn()
    try:
        if date_str:
            rows = conn.execute(
                "SELECT * FROM attendance_log WHERE date = ? ORDER BY logged_at",
                (date_str,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM attendance_log WHERE date = date('now') "
                "ORDER BY logged_at"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_attendance_range(start_date: str, end_date: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM attendance_log WHERE date BETWEEN ? AND ? "
            "ORDER BY date, logged_at",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_last_attendance(staff_id: str, date_str: str = None) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM attendance_log WHERE staff_id = ? "
            "AND date = COALESCE(?, date('now')) ORDER BY logged_at DESC LIMIT 1",
            (staff_id, date_str),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_attendance_summary(date_str: str = None) -> dict:
    conn = get_conn()
    try:
        total_staff = conn.execute(
            "SELECT COUNT(*) FROM staff WHERE active = 1"
        ).fetchone()[0]

        present = conn.execute(
            "SELECT COUNT(DISTINCT staff_id) FROM attendance_log "
            "WHERE date = COALESCE(?, date('now'))",
            (date_str,),
        ).fetchone()[0]

        return {
            "date": date_str or "today",
            "total_staff": total_staff,
            "present": present,
            "absent": total_staff - present,
            "attendance_pct": round(present / total_staff * 100, 1) if total_staff > 0 else 0,
        }
    finally:
        conn.close()


# --- Cameras ---

def add_camera(name: str, source_type: str, source_url: str = "",
               ip: str = "", port: int = 554, username: str = "",
               password: str = "", channel: int = 1,
               description: str = "") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO cameras (name, source_type, source_url, ip, port, "
            "username, password, channel, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, source_type, source_url, ip, port, username, password,
             channel, description),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_cameras(active_only: bool = True) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM cameras"
        if active_only:
            query += " WHERE active = 1"
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_camera(camera_id: int, **kwargs) -> bool:
    allowed = {"name", "source_type", "source_url", "ip", "port",
               "username", "password", "channel", "active", "description"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE cameras SET {set_clause} WHERE id = ?",
            (*values, camera_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_camera(camera_id: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
