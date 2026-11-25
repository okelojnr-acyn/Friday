"""A business's local time (owner, 2026-11-25): everything is stored in UTC;
days, months and the books follow the business's own time zone (kernel
core.orgs.time_zone). Viewers' screens convert to their own zone themselves.

    tz = await business_tz(org_id)
    entry_date = local_date(now, tz)          # the business's date
    start, end = day_bounds(day, tz)          # that local day, in UTC
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .settings import get_settings

_CACHE: dict[str, tuple[float, tzinfo]] = {}
_TTL = 600.0  # a business's zone rarely changes
_TTL_UNKNOWN = 60.0  # the kernel couldn't say: ask again soon


def zone(name: str) -> tzinfo:
    """The zone for an IANA name; UTC for "" or an unknown name."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


async def business_tz(org_id: str) -> tzinfo:
    """The business's time zone, cached; UTC when it isn't set or the
    kernel can't be asked (the last known zone is kept meanwhile)."""
    now = time.monotonic()
    hit = _CACHE.get(str(org_id))
    if hit and hit[0] > now:
        return hit[1]
    import httpx

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/orgs/{org_id}/time-zone",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            tz = zone(str(resp.json().get("time_zone") or ""))
        _CACHE[str(org_id)] = (now + _TTL, tz)
        return tz
    except (httpx.HTTPError, ValueError, KeyError):
        tz = hit[1] if hit else UTC
        _CACHE[str(org_id)] = (now + _TTL_UNKNOWN, tz)
        return tz


def local_date(at: datetime, tz: tzinfo) -> date:
    """The business's calendar date at instant `at` (naive = UTC)."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(tz).date()


def day_bounds(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """That local day as a UTC [start, end) window."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def month_bounds(year: int, month: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """That local month as a UTC [start, end) window."""
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def local_midnight(day: date, tz: tzinfo) -> datetime:
    """The start of a local day, in UTC (a date-only field such as a due date)."""
    return day_bounds(day, tz)[0]
