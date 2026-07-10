from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from src.config import EDITORIAL_TIMEZONE


def editorial_timezone() -> ZoneInfo:
    return ZoneInfo(EDITORIAL_TIMEZONE)


def editorial_today(now: datetime | None = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(editorial_timezone()).date()


def parse_reported_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def editorial_date(value: str | None) -> date | None:
    parsed = parse_reported_at(value)
    if parsed is None:
        return None
    return parsed.astimezone(editorial_timezone()).date()
