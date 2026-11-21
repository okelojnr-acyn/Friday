"""Selling on credit and paying debts (owner's plan, Guss follow-ups,
2026-11-21).

A credit sale is an unpaid POS sale against a customer (record_pos_sale
with on_credit). When the customer pays, the payment settles their
oldest unpaid sales first; a sale reaches the books (invoice.paid) when
it is paid in full, exactly like a typed invoice paid in parts.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .events import invoice_lines_payload, publish_invoice_paid
from .models import Customer, Invoice, Payment

router = APIRouter(prefix="/pos/debts", tags=["pos-sync"])


def _clean(name: str) -> str:
    return " ".join(name.split())[:120]


async def customer_by_name(session: AsyncSession, principal: Principal, name: str, create: bool) -> Customer | None:
    """The org's customer with this name (any case), or a new one."""
    name = _clean(name)
    if not name:
        return None
    rows = await session.execute(
        select(Customer)
        .where(Customer.org_id == uuid.UUID(principal.org_id), func.lower(Customer.name) == name.lower())
        .order_by(Customer.created_at)
    )
    found = rows.scalars().first()
    if found is not None or not create:
        return found
    found = Customer(org_id=uuid.UUID(principal.org_id), name=name, created_at=datetime.now(UTC))
    session.add(found)
    await session.flush()
    return found


async def _unpaid(session: AsyncSession, principal: Principal, customer_id: uuid.UUID | None = None) -> list[Invoice]:
    q = (
        select(Invoice)
        .where(
            Invoice.org_id == uuid.UUID(principal.org_id),
            Invoice.kind == "invoice",
            Invoice.status == "sent",
            Invoice.customer_id.is_not(None),
        )
        .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
        .order_by(Invoice.issued_at, Invoice.created_at)
    )
    if customer_id is not None:
        q = q.where(Invoice.customer_id == customer_id)
    return list((await session.execute(q)).scalars().all())


def _owed(inv: Invoice) -> int:
    return max(0, inv.grand_total_cents - inv.paid_cents)


@router.get("")
async def list_debts(
    customer: str | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Who owes what: every customer with unpaid sales or invoices, or one
    customer ("how much does John owe?"). A name that isn't a customer
    owes nothing."""
    customer_id = None
    if customer:
        c = await customer_by_name(session, principal, customer, create=False)
        if c is None:
            return []
        customer_id = c.id
    invoices = await _unpaid(session, principal, customer_id)
    names = {
        c.id: c.name
        for c in (
            await session.execute(select(Customer).where(Customer.id.in_({i.customer_id for i in invoices})))
        ).scalars()
    }
    out: dict[uuid.UUID, dict] = {}
    for inv in invoices:
        row = out.setdefault(
            inv.customer_id,
            {"customer": names.get(inv.customer_id, ""), "currency": inv.currency, "owed_cents": 0, "sales": []},
        )
        row["owed_cents"] += _owed(inv)
        row["sales"].append(
            {"number": inv.number, "issued_at": inv.issued_at, "total_cents": inv.grand_total_cents, "owed_cents": _owed(inv)}
        )
    return sorted(out.values(), key=lambda r: -r["owed_cents"])


@router.post("/payments", status_code=201)
async def pay_debt(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """A customer pays what they owe: {"customer_name", "amount_cents",
    "method", "client_payment_id"}. Settles their oldest unpaid sales
    first; a payment sent again with the same client_payment_id is
    recorded once. Paying more than is owed is refused."""
    ref = str(body.get("client_payment_id") or "").strip()[:120]
    method = str(body.get("method") or "cash").strip()[:16] or "cash"
    try:
        amount = int(body.get("amount_cents"))
    except (TypeError, ValueError):
        raise HTTPException(422, "amount_cents must be a whole number") from None
    if not ref:
        raise HTTPException(422, "client_payment_id is required")
    if amount <= 0:
        raise HTTPException(422, "the amount must be more than zero")
    customer = await customer_by_name(session, principal, str(body.get("customer_name") or ""), create=False)
    if customer is None:
        raise HTTPException(404, "no customer by that name owes anything")
    # One payment at a time per customer, so two retries can't both settle.
    await session.execute(select(Customer.id).where(Customer.id == customer.id).with_for_update())
    seen = await session.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.org_id == uuid.UUID(principal.org_id), Payment.client_ref == ref)
    )
    invoices = await _unpaid(session, principal, customer.id)
    owed = sum(_owed(i) for i in invoices)
    if seen:
        return {"customer": customer.name, "paid_cents": 0, "settled": [], "owed_cents": owed, "already_recorded": True}
    if owed == 0:
        raise HTTPException(409, f"{customer.name} owes nothing")
    if amount > owed:
        raise HTTPException(422, f"{customer.name} owes only {owed} cents")

    now = datetime.now(UTC)
    left = amount
    settled: list[Invoice] = []
    for inv in invoices:
        if left == 0:
            break
        part = min(left, _owed(inv))
        if part == 0:
            continue
        session.add(
            Payment(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=inv.id,
                amount_cents=part,
                method=method,
                received_at=now,
                client_ref=ref,
            )
        )
        left -= part
        if part == _owed(inv):
            inv.status = "paid"
            inv.updated_at = now
            settled.append(inv)
    await session.commit()
    for inv in settled:
        await session.refresh(inv, attribute_names=["lines", "payments"])
        await publish_invoice_paid(principal.org_id, inv, inv.paid_cents, invoice_lines_payload(inv))
    return {
        "customer": customer.name,
        "paid_cents": amount,
        "settled": [i.number for i in settled],
        "owed_cents": owed - amount,
        "already_recorded": False,
    }
