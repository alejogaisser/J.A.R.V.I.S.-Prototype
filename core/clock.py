"""Single authoritative clock for JARVIS in the user's local timezone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


JARVIS_TIMEZONE = timezone(timedelta(hours=-3), name="America/Buenos_Aires")


def local_now() -> datetime:
    """Return an aware datetime in Buenos Aires (Argentina has no current DST)."""
    return datetime.now(JARVIS_TIMEZONE)


def prompt_datetime(now: datetime | None = None) -> str:
    value = now or local_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=JARVIS_TIMEZONE)
    else:
        value = value.astimezone(JARVIS_TIMEZONE)
    if value.hour == 0:
        qualifier = "after midnight"
    elif value.hour < 12:
        qualifier = "morning"
    elif value.hour == 12:
        qualifier = "noon/early afternoon, not midnight"
    elif value.hour < 18:
        qualifier = "afternoon"
    else:
        qualifier = "evening/night"
    return (
        f"{value.strftime('%A, %B %d, %Y')} — "
        f"{value.strftime('%H:%M')} in 24-hour time "
        f"({value.strftime('%I:%M %p')}, {qualifier}) {value.strftime('%z')}"
    )
