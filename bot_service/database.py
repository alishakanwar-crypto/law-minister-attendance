"""Database layer for the Law Minister Bot standalone service."""

import aiosqlite
import logging

from bot_service.config import DB_PATH

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
    """Log a message to the database."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO message_log (direction, sender, recipient, message_type, content, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (direction, sender, recipient, msg_type, content[:500], category),
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log message: {e}")
    finally:
        await db.close()


async def get_messages(days: int = 7) -> list:
    """Get messages from the last N days."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM message_log WHERE timestamp >= datetime('now', ? || ' days') ORDER BY timestamp DESC",
            (f"-{days}",),
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
    """Add a new staff member."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO staff (name, phone, designation) VALUES (?, ?, ?) "
            "ON CONFLICT(phone) DO UPDATE SET name=excluded.name, designation=excluded.designation",
            (name, phone, designation),
        )
        await db.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to add staff: {e}")
        return False
    finally:
        await db.close()


async def get_attendance_records(date_str: str = "") -> list:
    """Get attendance records for a specific date or today."""
    db = await get_db()
    try:
        if date_str:
            cursor = await db.execute(
                "SELECT * FROM attendance WHERE date = ? ORDER BY time",
                (date_str,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM attendance WHERE date = date('now') ORDER BY time"
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()
