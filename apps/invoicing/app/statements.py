"""Customer statements and overdue reminders (roadmap item 5).

A statement is what a customer was sent and paid over a period, with the
balance carried in and a running balance: the page a bookkeeper prints
when a customer asks "what do I owe you?". Reminders go out by email 1, 7
and 14 days after an invoice falls due, until it's paid or voided.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from html import escape as html_escape

from fastapi import APIRouter, Depends, HTTPException, Query
from friday_common import (
    Principal,
    first_delivery,
    get_current_principal,
    get_integration_config,
    get_org_session,
    get_session,
    publish_event,
    require_kernel_token,
    set_org_context,
)
from friday_common.access import Scope, require
from friday_common.clock import business_tz, local_date, local_midnight
from friday_common.integrations import IntegrationConfigUnavailable, ResendProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Customer, Invoice

log = logging.getLogger("friday.invoicing.statements")

router = APIRouter(prefix="/customers", tags=["customers"])
hooks = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])

REMIND_AFTER_DUE = (timedelta(days=1), timedelta(days=7), timedelta(days=14))


def statement_rows(invoices: list, start: datetime, end: datetime) -> dict:
    """Opening balance before `start`, then each invoice (+) and payment (-)
    in [start, end) by date with a running balance, and the closing one.
    `invoices` are sent or paid invoices with lines and payments loaded."""
    events: list[tuple[datetime, str, str, int]] = []
    for inv in invoices:
        if inv.issued_at is not None:
            events.append((inv.issued_at, "invoice", inv.number, inv.grand_total_cents))
        for p in inv.payments:
            events.append((p.received_at, "payment", inv.number, -p.amount_cents))
    events.sort(key=lambda e: e[0])
    opening = sum(e[3] for e in events if e[0] < start)
    balance, rows = opening, []
    for at, kind, number, cents in events:
        if start <= at < end:
            balance += cents
            rows.append({"at": at, "kind": kind, "number": number, "amount_cents": cents, "balance_cents": balance})
    return {"opening_cents": opening, "rows": rows, "closing_cents": balance}


@router.get("/{customer_id}/statement")
async def customer_statement(
    customer_id: uuid.UUID,
    start: date | None = Query(None, description="First day (the business's calendar); 90 days ago by default"),
    end: date | None = Query(None, description="Last day, inclusive; today by default"),
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("customers.read")),
    session: AsyncSession = Depends(get_org_session),
):
    customer = await session.get(Customer, customer_id)
    if customer is None or str(customer.org_id) != principal.org_id:
        raise HTTPException(404, "customer not found")
    tz = await business_tz(principal.org_id)
    today = local_date(datetime.now(UTC), tz)
    last = end or today
    first = start or (last - timedelta(days=90))
    if first > last:
        raise HTTPException(422, "the start is after the end")
    invoices = (
        await session.execute(
            select(Invoice)
            .where(Invoice.customer_id == customer.id, Invoice.kind == "invoice", Invoice.status.in_(("sent", "paid")))
            .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
        )
    ).scalars().all()
    out = statement_rows(list(invoices), local_midnight(first, tz), local_midnight(last + timedelta(days=1), tz))
    currency = next((i.currency for i in invoices), "")
    return {"customer": customer.name, "currency": currency, "start": first, "end": last, **out}


async def schedule_reminders(session: AsyncSession, org_id: str, inv: Invoice) -> None:
    """When an invoice is sent with a due date: reminders after it falls
    due. Each checks, when it arrives, that the invoice is still unpaid.
    The caller commits."""
    if inv.kind != "invoice" or inv.due_at is None:
        return
    for i, after in enumerate(REMIND_AFTER_DUE):
        when = inv.due_at + after
        if when <= datetime.now(UTC):
            continue
        await publish_event(
            "invoicing.invoice.remind",
            org_id,
            {"invoice_id": str(inv.id), "nth": i + 1},
            session=session,
            deliver_at=when,
        )


@hooks.post("/invoice-remind", dependencies=[Depends(require_kernel_token)], status_code=204)
async def invoice_remind(body: dict, session: AsyncSession = Depends(get_session)):
    """A scheduled reminder (invoicing.invoice.remind): emails the customer
    if the invoice is still sent and owed. Best effort: no email on file
    or no email provider connected means no reminder, never an error."""
    org_id = body["org_id"]
    await set_org_context(session, org_id)
    if not await first_delivery(session, body):
        return
    payload = body.get("payload", {})
    inv = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == uuid.UUID(payload["invoice_id"]))
            .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
        )
    ).scalars().first()
    await session.commit()
    if inv is None or inv.status != "sent" or inv.balance_cents <= 0 or inv.customer_id is None:
        return
    customer = await session.get(Customer, inv.customer_id)
    try:
        config = await get_integration_config(org_id, "resend")
    except IntegrationConfigUnavailable as exc:
        log.warning("reminder for %s skipped: %s", inv.number, exc)
        return
    if customer is None or not customer.email or not config.get("api_key"):
        return
    days = (datetime.now(UTC) - inv.due_at).days if inv.due_at else 0
    html = (
        f"<p>Hi {html_escape(customer.name)},</p>"
        f"<p>A reminder that invoice <strong>{html_escape(inv.number)}</strong> for "
        f"<strong>{inv.balance_cents / 100:,.2f} {html_escape(inv.currency)}</strong> "
        f"was due {days} day{'s' if days != 1 else ''} ago.</p>"
    )
    if inv.pay_request_url:
        html += f'<p><a href="{html_escape(inv.pay_request_url)}">Pay online</a></p>'
    html += "<p>If you've already paid, thank you, and please ignore this.</p>"
    try:
        await ResendProvider(config).send(customer.email, f"Reminder: invoice {inv.number}", html)
    except Exception as exc:  # noqa: BLE001 -- a reminder must never fail the delivery
        log.warning("reminder for %s failed: %s", inv.number, exc)
