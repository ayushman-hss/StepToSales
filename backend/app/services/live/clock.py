"""One clock for live mode: India Standard Time, explicitly.

The history generators write IST dates and hours, so live events must too --
on a server whose system clock is UTC (most hosts), a naive datetime.now()
would put "today" five and a half hours out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Current IST wall-clock time, naive, to the second."""
    return datetime.now(IST).replace(tzinfo=None, microsecond=0)


def end_of_day(t: datetime) -> datetime:
    return t.replace(hour=23, minute=59, second=59, microsecond=0)
