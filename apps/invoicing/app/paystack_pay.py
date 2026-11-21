"""Paystack inside Friday (plan 15.3): the business's own Paystack takes
money for POS sales, invoice pay links and customer debts (a link Guss
sends in chat). One rule, as in Friday Host: a payment counts only after
Paystack's verify-by-reference says "success" in the right currency (and,
for a POS sale, the exact amount still due). The webhook, the till's
status poll and the debt-link check all end in `settle`/`settle_debt`,
so a lost webhook still settles and a repeated one is a no-op.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_integration_config, get_org_session
from friday_common.integrations import PaystackProvider
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .credit import _owed, _unpaid, apply_debt_payment, customer_by_name, rebook_ref
from .events import invoice_lines_payload, publish_invoice_paid, publish_pos_sale_recorded
from .models import Customer, Invoice, Payment

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pos", tags=["pos-sync"])

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REF_RE = re.compile(rf"^({_UUID})\.({_UUID})\.[0-9a-f]{{8}}$")
_DEBT_REF_RE = re.compile(rf"^({_UUID})\.debt-({_UUID})\.[0-9a-f]{{8}}$")
# Methods a cashier confirms by hand that can share a sale with Paystack.
SPLIT_METHODS = ("cash", "mpesa", "card")


def new_reference(org_id: str, invoice_id: uuid.UUID) -> str:
    """`<org>.<invoice>.<random>`: the webhook finds the org and invoice
    from it, and each attempt is unique so a retry never collides."""
    return f"{org_id}.{invoice_id}.{secrets.token_hex(4)}"


def new_debt_reference(org_id: str, customer_id: uuid.UUID) -> str:
    """`<org>.debt-<customer>.<random>`: a link for what a customer owes."""
    return f"{org_id}.debt-{customer_id}.{secrets.token_hex(4)}"


def parse_reference(reference: str) -> tuple[str, str] | None:
    m = _REF_RE.match(reference or "")
    return (m.group(1), m.group(2)) if m else None


def parse_debt_reference(reference: str) -> tuple[str, str] | None:
    m = _DEBT_REF_RE.match(reference or "")
    return (m.group(1), m.group(2)) if m else None


def method_for(channel: str) -> str:
    """Paystack's channel -> the payment method the books know (section
    14: M-Pesa lands in 1020, card and bank in 1030)."""
    # shortcut: every mobile_money payment books as M-Pesa (Airtel Money too); split it if a shop asks.
    if channel == "mobile_money":
        return "mpesa"
    if channel == "card":
        return "card"
    return "bank_transfer"


async def paystack_config(org_id: str) -> dict:
    config = await get_integration_config(org_id, "paystack")
    if not config.get("secret_key"):
        raise HTTPException(400, "Paystack is not connected -- add your secret key in Apps & integrations > Paystack")
    return config


async def _initialize(org_id: str, reference: str, amount_cents: int, currency: str, email: str, description: str) -> str:
    config = await paystack_config(org_id)
    try:
        intent = await PaystackProvider(config).create_payment_intent(
            amount_cents,
            currency,
            {"reference": reference, "email": email, "org_id": org_id, "description": description},
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(502, f"Could not start Paystack checkout: {exc}") from exc
    return intent["redirect_url"]


async def start_checkout(org_id: str, invoice: Invoice, amount_cents: int, email: str, description: str) -> str:
    """Opens a Paystack checkout for `amount_cents` of `invoice` and
    stores its reference on the invoice (the caller commits). Returns the
    page the customer pays on."""
    reference = new_reference(org_id, invoice.id)
    url = await _initialize(org_id, reference, amount_cents, invoice.currency, email, description)
    invoice.paystack_reference = reference
    return url


async def settle(session: AsyncSession, org_id: str, invoice_id: str, reference: str) -> None:
    """Asks Paystack about `reference` and, if it was paid, records the
    payment once. `session` must already be scoped to `org_id`."""
    config = await get_integration_config(org_id, "paystack")
    if not config.get("secret_key"):
        return
    provider = PaystackProvider(config)
    result = await provider.verify(reference)
    if result["status"] != "success":
        return

    # Locked so the webhook and a till's poll can't both record it.
    inv = await session.get(Invoice, uuid.UUID(invoice_id), with_for_update=True, populate_existing=True)
    if inv is None or str(inv.org_id) != org_id:
        log.warning("paystack %s paid but invoice %s is not found", reference, invoice_id)
        return
    await session.refresh(inv, attribute_names=["lines", "payments"])
    client_ref = f"paystack:{reference}"
    if any(p.client_ref == client_ref for p in inv.payments):
        return
    amount = result["amount"]
    if inv.status == "void" and inv.source == "pos" and amount > 0:
        # The cashier cancelled the sale and the customer paid anyway:
        # the money goes straight back rather than sitting unrecorded.
        try:
            await provider.refund(reference, amount)
            log.warning("paystack %s paid %s on cancelled sale %s; refunded", reference, amount, inv.number)
        except httpx.HTTPError as exc:
            log.warning("paystack %s paid on cancelled sale %s; refund failed: %s", reference, inv.number, exc)
        return
    pos_pending = inv.status == "pending"
    if inv.status == "void" or result["currency"] != inv.currency.upper() or amount <= 0:
        log.warning("paystack %s paid %s %s; invoice %s not settled", reference, amount, result["currency"], inv.number)
        return
    # A split sale took cash (or M-Pesa/card) at the till; Paystack the rest.
    if pos_pending and amount != inv.grand_total_cents - inv.paid_cents:
        log.warning("paystack %s paid %s, POS sale %s still owes %s", reference, amount, inv.number, inv.balance_cents)
        return

    now = datetime.now(UTC)
    session.add(
        Payment(
            org_id=inv.org_id,
            invoice_id=inv.id,
            amount_cents=amount,
            method=method_for(result["channel"]),
            received_at=now,
            client_ref=client_ref,
        )
    )
    await session.flush()
    await session.refresh(inv, attribute_names=["payments"])
    newly_paid = inv.paid_cents >= inv.grand_total_cents and inv.status != "paid"
    if newly_paid:
        inv.status = "paid"
        inv.updated_at = now
    await session.commit()
    if not newly_paid:
        return
    await session.refresh(inv, attribute_names=["lines", "payments"])
    if pos_pending:
        await publish_pos_sale_recorded(org_id, inv, inv.grand_total_cents)
        await publish_invoice_paid(org_id, inv, inv.grand_total_cents, invoice_lines_payload(inv))
    else:
        await publish_invoice_paid(
            org_id, inv, inv.paid_cents, invoice_lines_payload(inv), posting_ref=rebook_ref(inv, uuid.uuid4().hex)
        )


async def manual_tenders(session: AsyncSession, principal: Principal, invoice: Invoice, payments: list, charged: int) -> int:
    """The till's own part of a split sale (cash, M-Pesa to the till, PDQ
    card), recorded now; Paystack takes the rest. Returns what's left."""
    total = 0
    now = datetime.now(UTC)
    for p in payments or []:
        method = str(p.get("method") or "")
        try:
            cents = int(p.get("amount_cents"))
        except (TypeError, ValueError):
            raise HTTPException(422, "each payment needs a whole amount_cents") from None
        if method not in SPLIT_METHODS or cents <= 0:
            raise HTTPException(422, f"the till's part is paid by {', '.join(SPLIT_METHODS)}, more than zero")
        total += cents
        session.add(
            Payment(org_id=uuid.UUID(principal.org_id), invoice_id=invoice.id, amount_cents=cents, method=method, received_at=now)
        )
    if total >= charged:
        raise HTTPException(422, "the till's part already covers the sale; nothing is left for Paystack")
    return charged - total


@router.post("/sales/{invoice_id}/cancel")
async def cancel_pending_sale(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The customer won't pay on Paystack after all: the waiting sale is
    void and the till's part of a split (cash etc.) is handed back.
    Checked with Paystack first, so a sale the customer did pay is kept.
    If they pay after this, settle refunds it."""
    inv = await session.get(Invoice, invoice_id)
    if inv is None or str(inv.org_id) != principal.org_id:
        raise HTTPException(404, "sale not found")
    if inv.status != "pending":
        return {"invoice_id": str(inv.id), "status": inv.status, "returned_cents": 0}
    if not inv.paystack_reference:
        raise HTTPException(409, "a Pesapal sale confirms itself; wait for it")
    try:
        await settle(session, principal.org_id, str(inv.id), inv.paystack_reference)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not check with Paystack: {exc}") from exc
    inv = await session.get(Invoice, invoice_id, with_for_update=True, populate_existing=True)
    await session.refresh(inv, attribute_names=["payments"])
    if inv.status != "pending":
        return {"invoice_id": str(inv.id), "status": inv.status, "returned_cents": 0}
    returned = inv.paid_cents
    await session.execute(delete(Payment).where(Payment.invoice_id == inv.id))
    inv.status = "void"
    inv.updated_at = datetime.now(UTC)
    await session.commit()
    return {"invoice_id": str(inv.id), "status": "void", "returned_cents": returned}


async def refund_share(session: AsyncSession, org_id: str, original: Invoice, refund_cents: int) -> tuple[str, int] | None:
    """For a return of a sale Paystack was paid for: refunds through
    Paystack as much of `refund_cents` as Paystack took and hasn't given
    back yet, and returns (method, cents) for the books. None when the
    sale had no Paystack payment."""
    paid = [p for p in original.payments if (p.client_ref or "").startswith("paystack:") and p.amount_cents > 0]
    if not paid:
        return None
    reference = paid[0].client_ref.removeprefix("paystack:")
    taken = sum(p.amount_cents for p in paid)
    # Earlier returns of this sale that went back through Paystack carry
    # its method (mpesa/card/bank); the till's own refunds are "refund".
    rows = await session.execute(
        select(func.coalesce(func.sum(Payment.amount_cents), 0))
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Invoice.org_id == original.org_id,
            Invoice.source == "pos",
            Invoice.source_ref == original.number,
            Invoice.number.like("RET-%"),
            Payment.method != "refund",
        )
    )
    back = -int(rows.scalar_one())
    share = min(refund_cents, taken - back)
    if share <= 0:
        return None
    config = await paystack_config(org_id)
    try:
        await PaystackProvider(config).refund(reference, share)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Paystack refused the refund: {exc}") from exc
    return paid[0].method, share


class DebtLinkIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)


@router.post("/debts/paystack-link", status_code=201)
async def debt_link(
    body: DebtLinkIn,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """A Paystack page for everything a customer owes (Guss: "send John a
    pay link"). Paid money settles their oldest sales first, like a debt
    payment, once Paystack confirms it (GET .../{reference} or the
    webhook)."""
    customer = await customer_by_name(session, principal, body.customer_name, create=False)
    if customer is None:
        raise HTTPException(404, "no customer by that name owes anything")
    invoices = await _unpaid(session, principal, customer.id)
    owed = sum(_owed(i) for i in invoices)
    if owed == 0:
        raise HTTPException(409, f"{customer.name} owes nothing")
    currencies = {i.currency.upper() for i in invoices if _owed(i)}
    if len(currencies) != 1:
        raise HTTPException(409, f"{customer.name} owes in several currencies; send a link per invoice")
    currency = currencies.pop()
    reference = new_debt_reference(principal.org_id, customer.id)
    url = await _initialize(
        principal.org_id, reference, owed, currency, customer.email or principal.email or "", f"Balance for {customer.name}"
    )
    return {"customer": customer.name, "owed_cents": owed, "currency": currency, "reference": reference, "redirect_url": url}


async def settle_debt(session: AsyncSession, org_id: str, customer_id: str, reference: str) -> dict:
    """Asks Paystack about a debt link and records what was paid, once.
    `session` must already be scoped to `org_id`."""
    config = await get_integration_config(org_id, "paystack")
    if not config.get("secret_key"):
        return {"status": "not_connected"}
    result = await PaystackProvider(config).verify(reference)
    if result["status"] != "success":
        return {"status": result["status"] or "pending"}
    method = method_for(result["channel"])
    # One payment at a time per customer, as pay_debt does.
    customer = await session.get(Customer, uuid.UUID(customer_id), with_for_update=True)
    if customer is None or str(customer.org_id) != org_id:
        log.warning("paystack %s paid but customer %s is not found", reference, customer_id)
        return {"status": "unknown"}
    client_ref = f"paystack:{reference}"
    recorded = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.org_id == uuid.UUID(org_id), Payment.client_ref == client_ref
        )
    )
    paid = {"status": "paid", "customer": customer.name, "method": method, "currency": result["currency"]}
    if recorded:
        return {**paid, "paid_cents": int(recorded)}
    invoices = [
        i for i in await _unpaid(session, SimpleNamespace(org_id=org_id), customer.id) if i.currency.upper() == result["currency"]
    ]
    owed = sum(_owed(i) for i in invoices)
    amount = min(result["amount"], owed)
    if result["amount"] > owed:
        # shortcut: the extra (paid elsewhere meanwhile) is only logged; refund it by hand in Paystack.
        log.warning("paystack %s paid %s, %s owed only %s", reference, result["amount"], customer.name, owed)
    if amount > 0:
        await apply_debt_payment(session, org_id, invoices, amount, method, client_ref)
    return {**paid, "paid_cents": amount}


@router.get("/debts/paystack-link/{reference}")
async def check_debt_link(
    reference: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Has the customer paid this link? Records it the first time it's
    paid; Guss asks until then, so no webhook is needed."""
    parsed = parse_debt_reference(reference)
    if parsed is None or parsed[0] != principal.org_id:
        raise HTTPException(404, "not a pay link of this business")
    try:
        return await settle_debt(session, principal.org_id, parsed[1], reference)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not check with Paystack: {exc}") from exc
