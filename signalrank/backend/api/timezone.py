from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def resolve_timezone(name: str | None):
    text = (name or "").strip()
    if not text:
        return timezone.utc
    try:
        return ZoneInfo(text)
    except Exception:
        return timezone.utc


def format_datetime_local(value: datetime | None, tz_name: str | None) -> str | None:
    if value is None:
        return None
    tz = resolve_timezone(tz_name)
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(tz).isoformat()
