"""Database layer for the Law Minister Bot standalone service."""

import aiosqlite
import logging

from bot_service.config import DB_PATH
from bot_service.ist_time import now_iso, now_date_sql

logger = logging.getLogger("lm_bot.database")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    """Initialize all tables for the standalone bot."""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS message_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'text',
                content TEXT NOT NULL DEFAULT '',
                category TEXT DEFAULT '',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE,
                designation TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER,
                staff_name TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT DEFAULT 'present',
                snapshot_path TEXT DEFAULT '',
                notification_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (staff_id) REFERENCES staff(id)
            );

            CREATE TABLE IF NOT EXISTS face_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                image_path TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT DEFAULT '',
                embedding_synced INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_face_reg_phone ON face_registrations(phone);
            CREATE INDEX IF NOT EXISTS idx_face_reg_status ON face_registrations(status);

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            INSERT OR IGNORE INTO bot_settings (key, value) VALUES
                ('greeting_enabled', '1'),
                ('notifications_enabled', '1'),
                ('office_hours_start', '09:00'),
                ('office_hours_end', '18:00');
        """)

        await db.commit()
        logger.info("Database initialized successfully")
    finally:
        await db.close()


async def log_message(direction: str, sender: str, recipient: str,
                      content: str, msg_type: str = "text",
                      category: str = ""):
    """Log a message to the database with IST timestamp."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO message_log (direction, sender, recipient, message_type, content, category, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (direction, sender, recipient, msg_type, content[:500], category, now_iso()),
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
    finally:
        await db.close()


async def get_messages(days: int = 7) -> list:
    """Get messages from the last N days (IST-aware)."""
    from bot_service.ist_time import now, IST
    from datetime import timedelta
    cutoff = (now() - timedelta(days=days)).isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM message_log WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_staff_list() -> list:
    """Get all active staff members."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM staff WHERE is_active = 1 ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def add_staff(name: str, phone: str, designation: str = "") -> bool:
    """Add or update a staff member. One person per phone number."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM staff WHERE phone = ?", (phone,)
        )
        existing = await cursor.fetchone()
        if existing:
            await db.execute(
                "UPDATE staff SET name = ?, designation = ?, is_active = 1 WHERE id = ?",
                (name, designation, existing["id"]),
            )
        else:
            await db.execute(
                "INSERT INTO staff (name, phone, designation) VALUES (?, ?, ?)",
                (name, phone, designation),
            )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to add staff: {e}")
        return False
    finally:
        await db.close()


async def record_attendance(staff_name: str, phone: str, date_str: str, time_str: str) -> bool:
    """Record an attendance entry in the database."""
    db = await get_db()
    try:
        # Upsert staff record
        cursor = await db.execute("SELECT id FROM staff WHERE phone = ?", (phone,))
        row = await cursor.fetchone()
        if row:
            staff_id = row["id"]
        else:
            cursor = await db.execute(
                "INSERT INTO staff (name, phone) VALUES (?, ?)",
                (staff_name, phone),
            )
            await db.commit()
            staff_id = cursor.lastrowid

        await db.execute(
            "INSERT INTO attendance (staff_id, staff_name, date, time, status, notification_sent) "
            "VALUES (?, ?, ?, ?, 'present', 1)",
            (staff_id, staff_name, date_str, time_str),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to record attendance: {e}")
        return False
    finally:
        await db.close()


async def get_attendance_records(date_str: str = "") -> list:
    """Get attendance records for a specific date or today (IST).

    date_str format: DD-MM-YYYY (matches the format stored by notify-attendance).
    """
    from bot_service.ist_time import now
    db = await get_db()
    try:
        if not date_str:
            date_str = now().strftime("%d-%m-%Y")
        cursor = await db.execute(
            "SELECT * FROM attendance WHERE date = ? ORDER BY time",
            (date_str,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


# ---------- Face Registration ----------

async def add_face_registration(phone: str, name: str, image_path: str = "") -> bool:
    """Add a new face registration record with IST timestamp."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO face_registrations (phone, name, image_path, status, registered_at) "
            "VALUES (?, ?, ?, 'registered', ?)",
            (phone, name, image_path, now_iso()),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to add face registration: {e}")
        return False
    finally:
        await db.close()


async def update_face_registration(phone: str, name: str, image_path: str = "") -> bool:
    """Update the face registration for a phone number (one person per phone)."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE face_registrations SET name = ?, image_path = ?, "
            "status = 'registered', embedding_synced = 0, "
            "updated_at = ? WHERE phone = ?",
            (name, image_path, now_iso(), phone),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update face registration: {e}")
        return False
    finally:
        await db.close()


async def log_face_registration(phone: str, name: str, status: str,
                                reason: str = "", image_path: str = "") -> bool:
    """Log a face registration attempt (including rejections) with IST timestamp."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO face_registrations (phone, name, image_path, status, reason, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (phone, name, image_path, status, reason, now_iso()),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to log face registration: {e}")
        return False
    finally:
        await db.close()


async def get_face_registration_by_phone(phone: str) -> dict | None:
    """Get the latest face registration for a phone number."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM face_registrations WHERE phone = ? AND status = 'registered' "
            "ORDER BY updated_at DESC LIMIT 1",
            (phone,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def find_registrations_by_first_name(first_name: str) -> list:
    """Find all registered people whose first name matches (case-insensitive).

    Used when someone sends a first-name-only caption to check if an
    existing person shares that first name.
    """
    db = await get_db()
    try:
        # Match where the name starts with the given first name
        # (e.g. "Fatima" matches "Fatima Khan", "Fatima Ahmed")
        pattern = first_name.strip() + "%"
        cursor = await db.execute(
            "SELECT * FROM face_registrations "
            "WHERE LOWER(TRIM(name)) LIKE LOWER(?) AND status = 'registered' "
            "ORDER BY updated_at DESC",
            (pattern,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_all_registrations(status: str = "") -> list:
    """Get all face registrations, optionally filtered by status."""
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                "SELECT * FROM face_registrations WHERE status = ? ORDER BY registered_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM face_registrations ORDER BY registered_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_registration_stats() -> dict:
    """Get registration statistics."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT status, COUNT(*) as count FROM face_registrations GROUP BY status"
        )
        rows = await cursor.fetchall()
        stats = {row["status"]: row["count"] for row in rows}
        return {
            "total": sum(stats.values()),
            "registered": stats.get("registered", 0),
            "rejected": stats.get("rejected", 0),
            "pending": stats.get("pending", 0),
        }
    finally:
        await db.close()


async def get_pending_sync_registrations() -> list:
    """Get registrations that haven't been synced to the face engine."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM face_registrations "
            "WHERE status = 'registered' AND embedding_synced = 0 "
            "ORDER BY registered_at"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_registration_by_id(reg_id: int) -> dict | None:
    """Get a single face registration by its ID."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM face_registrations WHERE id = ?", (reg_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def mark_registration_synced(reg_id: int) -> bool:
    """Mark a registration as synced to the face recognition engine."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE face_registrations SET embedding_synced = 1 WHERE id = ?",
            (reg_id,),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to mark synced: {e}")
        return False
    finally:
        await db.close()
