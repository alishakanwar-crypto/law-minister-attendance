"""IST (Indian Standard Time) timestamp utility — single source of truth.

All timestamps in the Law Minister Bot system MUST use IST (UTC+5:30).
Never use UTC, server-local timezone, or device timezone.

Formats:
  Human-readable: DD-MM-YYYY HH:mm:ss IST
  ISO:            YYYY-MM-DDTHH:mm:ss+05:30
"""

from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    """Get current IST datetime."""
    return datetime.now(IST)


def now_human() -> str:
    """Get current IST in human-readable format: DD-MM-YYYY HH:mm:ss IST"""
    return datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S IST")


def now_iso() -> str:
    """Get current IST in ISO format: YYYY-MM-DDTHH:mm:ss+05:30"""
    return datetime.now(IST).isoformat()


def now_date() -> str:
    """Get current IST date: DD-MM-YYYY"""
    return datetime.now(IST).strftime("%d-%m-%Y")


def now_time() -> str:
    """Get current IST time: HH:mm:ss"""
    return datetime.now(IST).strftime("%H:%M:%S")


def now_time_12h() -> str:
    """Get current IST time in 12-hour format: hh:mm AM/PM IST"""
    return datetime.now(IST).strftime("%I:%M %p IST")


def now_date_sql() -> str:
    """Get current IST date in SQL-compatible format: YYYY-MM-DD"""
    return datetime.now(IST).strftime("%Y-%m-%d")


def now_timestamp_full() -> dict:
    """Get full timestamp bundle for logging/storage."""
    dt = datetime.now(IST)
    return {
        "human": dt.strftime("%d-%m-%Y %H:%M:%S IST"),
        "iso": dt.isoformat(),
        "unix": int(dt.timestamp()),
        "date": dt.strftime("%d-%m-%Y"),
        "time": dt.strftime("%H:%M:%S"),
        "time_12h": dt.strftime("%I:%M %p IST"),
    }


def format_dt_human(dt: datetime) -> str:
    """Format a datetime to human-readable IST string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.strftime("%d-%m-%Y %H:%M:%S IST")


def format_dt_iso(dt: datetime) -> str:
    """Format a datetime to ISO IST string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.isoformat()
