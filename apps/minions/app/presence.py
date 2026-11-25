"""Who's in today (HR plan phase 3): for the people a leader or manager
looks after, whether they've shown up today (a till sign-in, or Friday or
Minions opened), who's away on approved time off, and who hasn't been
seen yet. Presence only: there's no clock-out, so it says "last seen";
hours belong to Tally."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session
from friday_common.access import Scope, require
from friday_common.clock import business_tz, day_bounds, local_date, month_bounds
from friday_common.settings import get_settings
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Employee, EmployeeSale, TimeOff

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


# Team sales vs target (HR plan 8.2): this month's till and Guss sales per
# person (Minions' staff sales), against each person's monthly target.


class TargetSet(BaseModel):
    sales_target_cents: int = Field(ge=0, le=100_000_000_000)


@router.get("/sales")
async def team_sales(
    month: str | None = None,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("sales.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine (staff), my team's (team leaders), my locations' (managers),
    everyone's (owners): each person's sales this month (the business's
    calendar), their target, and the totals."""
    from .main import _visible_employee_ids

    tz = await business_tz(principal.org_id)
    if month:
        try:
            first = datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(422, "month is YYYY-MM") from None
    else:
        today = local_date(datetime.now(UTC), tz)
        first = datetime(today.year, today.month, 1)
    start, end = month_bounds(first.year, first.month, tz)
    q = select(Employee).where(Employee.org_id == uuid_of(principal), Employee.status == "active")
    ids = await _visible_employee_ids(session, principal, scope)
    if ids is not None:
        q = q.where(Employee.id.in_(ids))
    people = (await session.execute(q.order_by(Employee.name))).scalars().all()
    if not people:
        return {"month": f"{first.year}-{first.month:02d}", "people": [], "sold_cents": 0, "target_cents": 0}
    sums = {
        e_id: (total, n)
        for e_id, total, n in (
            await session.execute(
                select(EmployeeSale.employee_id, func.coalesce(func.sum(EmployeeSale.amount_cents), 0), func.count())
                .where(EmployeeSale.employee_id.in_([e.id for e in people]),
                       EmployeeSale.created_at >= start, EmployeeSale.created_at < end)
                .group_by(EmployeeSale.employee_id)
            )
        ).all()
    }
    rows = []
    for e in people:
        sold, n = sums.get(e.id, (0, 0))
        rows.append({"employee_id": str(e.id), "name": e.name, "sold_cents": int(sold), "sales": int(n),
                     "target_cents": e.sales_target_cents, "me": e.user_id == principal.user_id})
    rows.sort(key=lambda r: (-r["sold_cents"], r["name"].lower()))
    return {
        "month": f"{first.year}-{first.month:02d}",
        "people": rows,
        "sold_cents": sum(r["sold_cents"] for r in rows),
        "target_cents": sum(r["target_cents"] for r in rows),
    }


@router.put("/targets/{employee_id}")
async def set_target(
    employee_id: uuid.UUID,
    body: TargetSet,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("staff.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Whoever is over the person sets their monthly target (a team
    leader for their team, a manager for their locations, owners for
    anyone); nobody sets their own."""
    from .main import _visible_employee_ids

    e = await session.get(Employee, employee_id)
    if e is None or str(e.org_id) != principal.org_id:
        raise HTTPException(404, "employee not found")
    if e.user_id == principal.user_id and principal.role != "owner":
        raise HTTPException(403, "your target is set by whoever you report to")
    ids = await _visible_employee_ids(session, principal, scope)
    if ids is not None and e.id not in ids:
        raise HTTPException(403, f"{e.name} isn't in your team or locations")
    e.sales_target_cents = body.sales_target_cents
    e.updated_at = datetime.now(UTC)
    await session.commit()
    return {"employee_id": str(e.id), "sales_target_cents": e.sales_target_cents}
