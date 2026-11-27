"""Registers (tills) and their shifts.

Each register has one drawer, so one open shift at a time
(idx_pos_shifts_one_open_per_register). A cashier opens the register with
the cash float they counted into the drawer; sales and returns rung up on
it carry the shift's id; closing asks for the counted cash *before*
showing what was expected (a blind count, so the count is honest), then
records the difference and a summary by payment method.

Expected cash = opening float + cash taken in this shift's sales + this
shift's returns. POS returns are paid back from the drawer at the till,
so their (negative) refund payments count as cash out.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session, publish_event
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from friday_common.access import Scope, require, spending_policy

from .models import Invoice, Payment, PosHandover, PosPaidOut, PosRegister, PosShift
from .schemas import PosShiftOut

router = APIRouter(prefix="/pos", tags=["pos-registers"])

# What a business or a till can offer (plan 15.3). The kernel's org
# settings check the same list for the business's own choice.
TILL_METHODS = ("cash", "mpesa", "card", "paystack", "pesapal")

NO_TILLS = "no tills set up yet: an owner or admin adds them in Friday under Business settings > Tills"


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    location_name: str = Field(default="", max_length=80)
    location_id: uuid.UUID | None = None


class RegisterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    location_name: str | None = Field(default=None, max_length=80)
    active: bool | None = None
    location_id: uuid.UUID | None = None
    # null puts the till back on the business's list.
    payment_methods: list[str] | None = None


class RegisterOut(BaseModel):
    id: uuid.UUID
    name: str
    location_name: str
    active: bool
    location_id: uuid.UUID | None = None
    payment_methods: list[str] | None = None
    open_shift: PosShiftOut | None = None


class ShiftOpenIn(BaseModel):
    register_id: uuid.UUID | None = None
    opening_float_cents: int = Field(ge=0, default=0)


class ShiftCloseIn(BaseModel):
    closing_count_cents: int = Field(ge=0)
    note: str = Field(default="", max_length=500)


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def _open_shift(session: AsyncSession, org_id: uuid.UUID, register_id: uuid.UUID) -> PosShift | None:
    rows = await session.execute(
        select(PosShift).where(
            PosShift.org_id == org_id, PosShift.register_id == register_id, PosShift.status == "open"
        )
    )
    return rows.scalars().first()


async def _register(session: AsyncSession, principal: Principal, register_id: uuid.UUID) -> PosRegister:
    reg = await session.get(PosRegister, register_id)
    if reg is None or str(reg.org_id) != principal.org_id:
        raise HTTPException(404, "register not found")
    return reg


async def _default_register(session: AsyncSession, principal: Principal) -> PosRegister:
    """The org's only till, when a request names none. Tills are set up
    by an owner or admin (Business settings > Tills); the POS never makes
    one up (owner, 2026-11-16)."""
    rows = await session.execute(
        select(PosRegister).where(PosRegister.org_id == _org(principal), PosRegister.active).order_by(
            PosRegister.created_at
        )
    )
    regs = rows.scalars().all()
    if len(regs) == 1:
        return regs[0]
    if len(regs) > 1:
        raise HTTPException(400, "this organisation has several registers; choose which one this till is")
    raise HTTPException(400, NO_TILLS)


@router.get("/registers", response_model=list[RegisterOut])
async def list_registers(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    regs = (
        await session.execute(
            select(PosRegister).where(PosRegister.org_id == _org(principal)).order_by(
                PosRegister.location_name, PosRegister.name
            )
        )
    ).scalars().all()
    open_shifts = {
        s.register_id: s
        for s in (
            await session.execute(
                select(PosShift).where(PosShift.org_id == _org(principal), PosShift.status == "open")
            )
        ).scalars()
    }
    return [
        RegisterOut(
            id=r.id,
            name=r.name,
            location_name=r.location_name,
            active=r.active,
            location_id=r.location_id,
            payment_methods=r.payment_methods,
            open_shift=PosShiftOut.model_validate(open_shifts[r.id]) if r.id in open_shifts else None,
        )
        for r in regs
    ]


@router.post("/registers", response_model=RegisterOut, status_code=201)
async def create_register(
    body: RegisterIn,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("tills.write")),
    session: AsyncSession = Depends(get_org_session),
):
    if not scope.everywhere:
        if body.location_id is None:
            raise HTTPException(422, "choose which of your locations the till stands in")
        at_place(scope, body.location_id)
    reg = PosRegister(
        org_id=_org(principal),
        name=body.name.strip(),
        location_name=body.location_name.strip(),
        location_id=body.location_id,
        created_at=datetime.now(UTC),
    )
    session.add(reg)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, f"there's already a register called {body.name.strip()!r}") from None
    return RegisterOut(
        id=reg.id, name=reg.name, location_name=reg.location_name, active=reg.active, location_id=reg.location_id
    )


@router.patch("/registers/{register_id}", response_model=RegisterOut)
async def update_register(
    register_id: uuid.UUID,
    body: RegisterPatch,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("tills.write")),
    session: AsyncSession = Depends(get_org_session),
):
    reg = await _register(session, principal, register_id)
    if not scope.everywhere:
        if reg.location_id is None:
            raise HTTPException(403, "only an owner or admin changes a till that isn't placed at a location")
        at_place(scope, reg.location_id)
    if "location_id" in body.model_fields_set:
        if body.location_id is None and not scope.everywhere:
            raise HTTPException(422, "a till of yours stays at one of your locations")
        if body.location_id is not None:
            at_place(scope, body.location_id)
        reg.location_id = body.location_id
    if body.name is not None:
        reg.name = body.name.strip()
    if body.location_name is not None:
        reg.location_name = body.location_name.strip()
    if body.active is not None:
        if not body.active and await _open_shift(session, _org(principal), reg.id):
            raise HTTPException(400, "close this register's shift before switching it off")
        reg.active = body.active
    if "payment_methods" in body.model_fields_set:
        methods = body.payment_methods
        if methods is not None:
            bad = [m for m in methods if m not in TILL_METHODS]
            if bad or not methods:
                raise HTTPException(422, f"payment methods are some of {', '.join(TILL_METHODS)}")
            methods = list(dict.fromkeys(methods))
        reg.payment_methods = methods
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "there's already a register with that name") from None
    return RegisterOut(
        id=reg.id,
        name=reg.name,
        location_name=reg.location_name,
        active=reg.active,
        location_id=reg.location_id,
        payment_methods=reg.payment_methods,
    )


@router.get("/shifts", response_model=list[PosShiftOut])
async def list_shifts(
    register_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("sales.read")),
    session: AsyncSession = Depends(get_org_session),
):
    q = select(PosShift).where(PosShift.org_id == _org(principal))
    if register_id:
        q = q.where(PosShift.register_id == register_id)
    rows = await session.execute(q.order_by(PosShift.opened_at.desc()).limit(200))
    return rows.scalars().all()


@router.get("/shifts/current", response_model=PosShiftOut)
async def current_shift(
    register_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    reg = await _register(session, principal, register_id) if register_id else await _default_register(session, principal)
    shift = await _open_shift(session, _org(principal), reg.id)
    if shift is None:
        raise HTTPException(404, "no open shift")
    return shift


@router.post("/shifts/open", response_model=PosShiftOut, status_code=201)
async def open_shift(
    body: ShiftOpenIn,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    reg = (
        await _register(session, principal, body.register_id)
        if body.register_id
        else await _default_register(session, principal)
    )
    if not reg.active:
        raise HTTPException(400, "this register is switched off")
    at_place(scope, reg.location_id)
    if await _open_shift(session, _org(principal), reg.id):
        raise HTTPException(409, f"{reg.name} is already open; close it before opening it again")
    shift = PosShift(
        org_id=_org(principal),
        register_id=reg.id,
        opened_at=datetime.now(UTC),
        opening_float_cents=body.opening_float_cents,
        status="open",
        opened_by_user_id=principal.user_id,
        opened_by_email=principal.email,
    )
    session.add(shift)
    try:
        await session.commit()
    except IntegrityError:  # two tills opening the same register at once
        raise HTTPException(409, f"{reg.name} was just opened on another device") from None
    await session.refresh(shift)
    return shift


async def shift_summary(session: AsyncSession, shift: PosShift) -> dict:
    """Takings of one shift by payment method, from its own sales."""
    rows = await session.execute(
        select(Payment.method, func.count(Payment.id), func.coalesce(func.sum(Payment.amount_cents), 0))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Invoice.pos_shift_id == shift.id)
        .group_by(Payment.method)
    )
    by_method = {m: {"count": int(c), "cents": int(t)} for m, c, t in rows.all()}
    counts = await session.execute(
        select(Invoice.number, Invoice.status).where(Invoice.pos_shift_id == shift.id)
    )
    sales = returns = 0
    for number, _status in counts.all():
        if number.startswith("RET-"):
            returns += 1
        else:
            sales += 1
    cash = by_method.get("cash", {}).get("cents", 0)
    refunds = by_method.get("refund", {}).get("cents", 0)  # negative
    paid_out = await session.scalar(
        select(func.coalesce(func.sum(PosPaidOut.amount_cents), 0)).where(PosPaidOut.shift_id == shift.id)
    )
    # Cash taken per cashier, so a shared drawer's takings are split by
    # who rang them up (plan 20.3).
    per = await session.execute(
        select(Invoice.cashier_email, func.coalesce(func.sum(Payment.amount_cents), 0))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Invoice.pos_shift_id == shift.id, Payment.method.in_(("cash", "refund")))
        .group_by(Invoice.cashier_email)
    )
    handovers = (
        await session.execute(
            select(PosHandover).where(PosHandover.shift_id == shift.id).order_by(PosHandover.created_at)
        )
    ).scalars().all()
    return {
        "by_method": by_method,
        "sales": sales,
        "returns": returns,
        "paid_out_cents": int(paid_out),
        "expected_cash_cents": shift.opening_float_cents + cash + refunds - int(paid_out),
        "cash_by_cashier": {(e or "unknown"): int(c) for e, c in per.all()},
        "handovers": handover_stretches(
            [(h.by_email, h.counted_cents, h.expected_cents, h.created_at.isoformat()) for h in handovers]
        ),
    }


def handover_stretches(rows: list[tuple[str, int, int, str]]) -> list[dict]:
    """Each handover's over/short for its own stretch: the drawer's running
    difference (counted - expected) now, less what it already was at the
    previous handover, so one cashier's shortage isn't carried by the next."""
    out, before = [], 0
    for email, counted, expected, at in rows:
        diff = counted - expected
        out.append({"by": email, "at": at, "counted_cents": counted, "expected_cents": expected, "short_cents": diff - before})
        before = diff
    return out


class HandoverIn(BaseModel):
    counted_cents: int = Field(ge=0)
    note: str = Field(default="", max_length=500)


@router.post("/shifts/{shift_id}/handover")
async def hand_over(
    shift_id: uuid.UUID,
    body: HandoverIn,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """The outgoing cashier's blind count when the cashier changes mid-
    shift. Answers what was expected and this stretch's over/short."""
    shift = (
        await session.execute(select(PosShift).where(PosShift.id == shift_id).with_for_update())
    ).scalars().first()
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(404, "shift not found")
    if shift.status != "open":
        raise HTTPException(400, "this shift is already closed")
    await till_location_check(session, scope, shift)
    summary = await shift_summary(session, shift)
    session.add(
        PosHandover(
            org_id=shift.org_id,
            shift_id=shift.id,
            counted_cents=body.counted_cents,
            expected_cents=summary["expected_cash_cents"],
            by_user_id=principal.user_id or "",
            by_email=principal.email or "",
            note=body.note.strip(),
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    stretches = (await shift_summary(session, shift))["handovers"]
    await session.commit()
    return stretches[-1]


@router.get("/shifts/{shift_id}", response_model=PosShiftOut)
async def get_shift(
    shift_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("sales.read")),
    session: AsyncSession = Depends(get_org_session),
):
    shift = await session.get(PosShift, shift_id)
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(404, "shift not found")
    return shift


@router.post("/shifts/{shift_id}/close", response_model=PosShiftOut)
async def close_shift(
    shift_id: uuid.UUID,
    body: ShiftCloseIn,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    # Locked, so two closes (or a close racing a late sale's lookup) can't
    # both compute a summary.
    shift = (
        await session.execute(select(PosShift).where(PosShift.id == shift_id).with_for_update())
    ).scalars().first()
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(404, "shift not found")
    if shift.status != "open":
        raise HTTPException(400, "this shift is already closed")
    summary = await shift_summary(session, shift)
    shift.closed_at = datetime.now(UTC)
    shift.closing_count_cents = body.closing_count_cents
    shift.expected_cents = summary["expected_cash_cents"]
    shift.closed_by_user_id = principal.user_id
    shift.closed_by_email = principal.email
    shift.close_note = body.note.strip()
    shift.summary = summary
    shift.status = "closed"
    await session.commit()
    await session.refresh(shift)
    return shift


def at_place(scope: Scope, location_id, what: str = "that till") -> None:
    """Refuses a till or sale outside the caller's locations. A till nobody
    has placed yet (no location) stays open to everyone allowed to sell."""
    if location_id is not None and not scope.allows_location(str(location_id)):
        raise HTTPException(403, f"{what} is at a location that isn't yours")


async def till_location(session: AsyncSession, shift_id: uuid.UUID | None):
    """The location of the till a shift runs on (None if not set)."""
    if shift_id is None:
        return None
    shift = await session.get(PosShift, shift_id)
    if shift is None or shift.register_id is None:
        return None
    reg = await session.get(PosRegister, shift.register_id)
    return reg.location_id if reg else None


async def shift_for_sale(session: AsyncSession, principal: Principal, raw: object) -> uuid.UUID | None:
    """The shift a sale names, if it's this org's. A sale made offline may
    arrive after its shift closed; it still belongs to that shift. A sale
    from an older till build names none: it joins the org's open shift
    when there is exactly one (a one-till shop), else stays unassigned."""
    if not raw:
        open_ids = (
            await session.execute(
                select(PosShift.id).where(PosShift.org_id == _org(principal), PosShift.status == "open").limit(2)
            )
        ).scalars().all()
        return open_ids[0] if len(open_ids) == 1 else None
    try:
        sid = uuid.UUID(str(raw))
    except ValueError:
        raise HTTPException(422, "shift_id is not a valid id") from None
    shift = await session.get(PosShift, sid)
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(422, "shift_id is not a shift of this organisation")
    return sid


class PaidOutIn(BaseModel):
    amount_cents: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=200)
    category: str = Field(default="other", max_length=20)


class PaidOutOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    description: str
    category: str
    by_email: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/shifts/{shift_id}/paid_outs", response_model=PaidOutOut, status_code=201)
async def pay_out_of_the_till(
    shift_id: uuid.UUID,
    body: PaidOutIn,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """Cash out of the drawer for a small business spend, only when the
    spending policy allows it (off by default) and at most its most for one
    slip. It's on the shift (less cash expected) and in the books (Dr 6900
    Shop expenses, Cr Cash)."""
    policy = await spending_policy(principal.org_id)
    if not policy["till_payouts"]:
        raise HTTPException(403, "paying out of the till is off; use petty cash (an owner can allow it in Business settings > Spending)")
    most = int(policy["petty_slip_max"])
    if body.amount_cents > most:
        raise HTTPException(422, f"the till pays out at most {most / 100:,.0f} at a time")
    shift = (await session.execute(select(PosShift).where(PosShift.id == shift_id).with_for_update())).scalars().first()
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(404, "shift not found")
    if shift.status != "open":
        raise HTTPException(400, "this shift is closed")
    await till_location_check(session, scope, shift)
    out = PosPaidOut(org_id=shift.org_id, shift_id=shift.id, amount_cents=body.amount_cents,
                     description=body.description.strip(), category=body.category, by_user_id=principal.user_id,
                     by_email=principal.email, created_at=datetime.now(UTC))
    session.add(out)
    await session.flush()
    await publish_event(
        "invoicing.till.paid_out",
        principal.org_id,
        {"paid_out_id": str(out.id), "amount_cents": out.amount_cents, "description": out.description, "category": out.category},
        session=session,
    )
    await session.commit()
    await session.refresh(out)
    return out


async def till_location_check(session: AsyncSession, scope: Scope, shift: PosShift) -> None:
    if shift.register_id:
        reg = await session.get(PosRegister, shift.register_id)
        if reg is not None:
            at_place(scope, reg.location_id)


@router.get("/shifts/{shift_id}/paid_outs", response_model=list[PaidOutOut])
async def list_paid_outs(
    shift_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PosPaidOut).where(PosPaidOut.org_id == uuid.UUID(principal.org_id), PosPaidOut.shift_id == shift_id)
        .order_by(PosPaidOut.created_at)
    )
    return rows.scalars().all()
