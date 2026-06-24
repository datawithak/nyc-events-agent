"""Date parsing / TZ helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from dateutil import parser as dateparser
from dateutil import tz

NY = tz.gettz("America/New_York")
UTC = timezone.utc


def parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return dateparser.parse(value)
    except (ValueError, TypeError):
        return None


def to_utc_iso(value: Optional[str | datetime], assume_tz=NY) -> Optional[str]:
    dt = value if isinstance(value, datetime) else parse(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(UTC).isoformat()


def to_local_iso(value: Optional[str | datetime], assume_tz=NY) -> Optional[str]:
    dt = value if isinstance(value, datetime) else parse(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt.astimezone(NY).isoformat()


def now_utc() -> datetime:
    return datetime.now(UTC)
