"""Paystack inside Friday (plan 15.3): the business's own Paystack takes
money for POS sales and invoice pay links. One rule, as in Friday Host:
a payment counts only after Paystack's verify-by-reference says
"success" in the invoice's currency (and, for a POS sale, the exact
amount). The webhook and the till's status poll both end in `settle`,
so a lost webhook still settles and a repeated one is a no-op.
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from friday_common import get_integration_config
from friday_common.integrations import PaystackProvider
from sqlalchemy.ext.asyncio import AsyncSession

from .credit import rebook_ref
from .events import invoice_lines_payload, publish_invoice_paid, publish_pos_sale_recorded
from .models import Invoice, Payment

log = logging.getLogger(__name__)

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REF_RE = re.compile(rf"^({_UUID})\.({_UUID})\.[0-9a-f]{{8}}$")


def new_reference(org_id: str, invoice_id: uuid.UUID) -> str:
    """`<org>.<invoice>.<random>`: the webhook finds the org and invoice
    from it, and each attempt is unique so a retry never collides."""
    return f"{org_id}.{invoice_id}.{secrets.token_hex(4)}"


def parse_reference(reference: str) -> tuple[str, str] | None:
    m = _REF_RE.match(reference or "")
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
        raise HTTPException(400, "Paystack is not connected -- add your secret key in Settings > Integrations")
    return config


async def start_checkout(org_id: str, invoice: Invoice, amount_cents: int, email: str, description: str) -> str:
    """Opens a Paystack checkout for `amount_cents` of `invoice` and
    stores its reference on the invoice (the caller commits). Returns the
    page the customer pays on."""
    config = await paystack_config(org_id)
    reference = new_reference(org_id, invoice.id)
    try:
        intent = await PaystackProvider(config).create_payment_intent(
            amount_cents,
            invoice.currency,
            {
                "reference": reference,
                "email": email,
                "invoice_id": str(invoice.id),
                "org_id": org_id,
                "description": description,
            },
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(502, f"Could not start Paystack checkout: {exc}") from exc
    invoice.paystack_reference = reference
    return intent["redirect_url"]


async def settle(session: AsyncSession, org_id: str, invoice_id: str, reference: str) -> None:
    """Asks Paystack about `reference` and, if it was paid, records the
    payment once. `session` must already be scoped to `org_id`."""
    config = await get_integration_config(org_id, "paystack")
    if not config.get("secret_key"):
        return
    result = await PaystackProvider(config).verify(reference)
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
    pos_pending = inv.status == "pending"
    if inv.status == "void" or result["currency"] != inv.currency.upper() or amount <= 0:
        log.warning("paystack %s paid %s %s; invoice %s not settled", reference, amount, result["currency"], inv.number)
        return
    if pos_pending and amount != inv.grand_total_cents:
        log.warning("paystack %s paid %s, POS sale %s is %s", reference, amount, inv.number, inv.grand_total_cents)
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
        await publish_pos_sale_recorded(org_id, inv, amount)
        await publish_invoice_paid(org_id, inv, amount, invoice_lines_payload(inv))
    else:
        await publish_invoice_paid(
            org_id, inv, inv.paid_cents, invoice_lines_payload(inv), posting_ref=rebook_ref(inv, uuid.uuid4().hex)
        )
