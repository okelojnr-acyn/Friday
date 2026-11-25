"""Who's in today (HR plan phase 3): for the people a leader or manager
looks after, whether they've shown up today (a till sign-in, or Friday or
Minions opened), who's away on approved time off, and who hasn't been
seen yet. Presence only: there's no clock-out, so it says "last seen";
hours belong to Tally."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session
from friday_common.access import Scope, require
from friday_common.clock import business_tz, day_bounds, local_date
from friday_common.settings import get_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Employee, TimeOff

router = APIRouter(prefix="/team", tags=["team"])


async def _seen(org_id: str, since: datetime, user_ids: list[str]) -> dict[str, dict]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/people/{org_id}/seen",
                params=[("since", since.isoformat()), *(("user_id", u) for u in user_ids)],
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            return {s["user_id"]: s for s in resp.json()}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, f"couldn't check who's in: {exc}") from exc


@router.get("/today")
async def whos_in_today(
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("staff.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """The people I look after (a team leader's team, a manager's
    locations, everyone for owners), each: in (at which till, since when,
    last seen), away (what kind of leave), or not seen yet today."""
    from .main import _visible_employee_ids  # shared with the staff list

    tz = await business_tz(principal.org_id)
    today = local_date(datetime.now(UTC), tz)
    since, _ = day_bounds(today, tz)
    q = select(Employee).where(Employee.org_id == uuid_of(principal), Employee.status == "active", Employee.user_id != "")
    ids = await _visible_employee_ids(session, principal, scope)
    if ids is not None:
        q = q.where(Employee.id.in_(ids))
    people = [e for e in (await session.execute(q.order_by(Employee.name))).scalars().all() if e.user_id != principal.user_id]
    if not people:
        return []
    away = {
        e_id: kind
        for e_id, kind in (
            await session.execute(
                select(TimeOff.employee_id, TimeOff.kind).where(
                    TimeOff.employee_id.in_([e.id for e in people]), TimeOff.status == "approved",
                    TimeOff.starts_on <= today, TimeOff.ends_on >= today,
                )
            )
        ).all()
    }
    seen = await _seen(principal.org_id, since, [e.user_id for e in people])
    out = []
    for e in people:
        s = seen.get(e.user_id)
        row = {"employee_id": str(e.id), "name": e.name, "department": e.department}
        if e.id in away:
            row.update(state="away", leave=away[e.id])
        elif s:
            row.update(state="in", till=s.get("till") or "", since=s.get("till_at") or s.get("app_first_at"), last_seen=s.get("last_at"))
        else:
            row.update(state="not_yet")
        out.append(row)
    order = {"in": 0, "not_yet": 1, "away": 2}
    return sorted(out, key=lambda r: (order[r["state"]], r["name"].lower()))


def uuid_of(principal: Principal):
    import uuid

    return uuid.UUID(principal.org_id)
