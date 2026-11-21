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

from friday_common.access import Scope, require

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


async def _unpaid(session: AsyncSession, principal, customer_id: uuid.UUID | None = None) -> list[Invoice]:
    """`principal` only needs .org_id (paystack_pay passes the org alone)."""
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


REVERSED = ":reversed"


def rebook_ref(inv: Invoice, key: str) -> str | None:
    """Accounting books an invoice once by its id. After one of its
    payments was reversed (its booking undone), paying it again needs its
    own posting ref, or the new booking would be skipped."""
    if any((p.client_ref or "").endswith(REVERSED) for p in inv.payments):
        return f"{inv.id}:{key}"
    return None


@router.get("")
async def list_debts(
    customer: str | None = None,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("customers.read")),
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


async def apply_debt_payment(
    session: AsyncSession, org_id: str, invoices: list[Invoice], amount: int, method: str, ref: str
) -> list[Invoice]:
    """Spreads `amount` over `invoices` (oldest first, as _unpaid returns
    them), commits, and books each sale it settles. Every row carries
    `ref`, so the caller's "seen it already" check stays one query. The
    caller holds the customer's row lock and checks amount <= owed."""
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
                org_id=uuid.UUID(org_id),
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
        await publish_invoice_paid(
            org_id, inv, inv.paid_cents, invoice_lines_payload(inv), posting_ref=rebook_ref(inv, ref)
        )
    return settled


@router.post("/payments", status_code=201)
async def pay_debt(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("customers.write")),
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

    settled = await apply_debt_payment(session, principal.org_id, invoices, amount, method, ref)
    return {
        "customer": customer.name,
        "paid_cents": amount,
        "settled": [i.number for i in settled],
        "owed_cents": owed - amount,
        "already_recorded": False,
    }


@router.post("/payments/{client_payment_id}/reverse", status_code=201)
async def reverse_debt_payment(
    client_payment_id: str,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("customers.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Takes back a debt payment recorded in error (Guss: /void of "John
    paid 500"). Each sale it paid toward owes that much again; a sale it
    had settled is unpaid again and its booking is reversed exactly. Sent
    twice, it reverses once. Never recorded: 404."""
    ref = client_payment_id.strip()[:120]
    org = uuid.UUID(principal.org_id)
    rows = (
        await session.execute(
            select(Payment).where(Payment.org_id == org, Payment.client_ref.in_([ref, ref + REVERSED]))
        )
    ).scalars().all()
    paid = [p for p in rows if p.client_ref == ref]
    if not paid:
        raise HTTPException(404, "no payment with that id")
    if any(p.client_ref == ref + REVERSED for p in rows):
        return {"reversed_cents": 0, "reopened": [], "already_reversed": True}

    invoices = {
        inv.id: inv
        for inv in (
            await session.execute(
                select(Invoice)
                .where(Invoice.id.in_({p.invoice_id for p in paid}))
                .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
                .with_for_update()
            )
        ).scalars()
    }
    if any(inv.status == "void" for inv in invoices.values()):
        raise HTTPException(409, "a sale this payment went to was cancelled; correct it in Invoicing")

    now = datetime.now(UTC)
    to_unbook: list[tuple[Invoice, list[Payment]]] = []
    for inv in invoices.values():
        if inv.status == "paid":
            # Its booking listed the payments as they were; mirror exactly that.
            to_unbook.append((inv, list(inv.payments)))
            inv.status = "sent"
            inv.updated_at = now
    for p in paid:
        session.add(
            Payment(
                org_id=org,
                invoice_id=p.invoice_id,
                amount_cents=-p.amount_cents,
                method=p.method,
                received_at=now,
                client_ref=ref + REVERSED,
            )
        )
    await session.commit()
    for inv, booked in to_unbook:
        await session.refresh(inv, attribute_names=["lines", "payments"])
        total = sum(b.amount_cents for b in booked)
        lines = [{**line, "quantity": -line["quantity"]} for line in invoice_lines_payload(inv)]
        await publish_invoice_paid(
            principal.org_id, inv, -total, lines, posting_ref=f"{inv.id}{REVERSED}:{ref}", sign=-1, payments=booked
        )
    return {
        "reversed_cents": sum(p.amount_cents for p in paid),
        "reopened": [inv.number for inv, _ in to_unbook],
        "already_reversed": False,
    }
