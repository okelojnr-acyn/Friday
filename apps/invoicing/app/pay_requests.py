"""Pay requests (reliability plan 6.1; owner 2026-11-26: every provider the
same). Sending an invoice to a customer with an email asks the business's
payment provider to request the money: a Paystack Payment Request, a Stripe
Invoice or a Pesapal order. Paystack and Stripe email the customer and show
it "pending"; Pesapal's page goes in Friday's own invoice email.

It counts as paid only when the provider's own status call says so. Friday
asks on a schedule (kernel delayed events, sooner at first, then daily up
to 30 days), so nothing depends on a webhook's undocumented body; Stripe's
signed invoice.paid only makes it sooner. A new request cancels the last.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from friday_common import first_delivery, get_integration_config, get_session, publish_event, require_kernel_token, set_org_context
from friday_common.integrations import PaystackProvider, PesapalProvider, StripeProvider
from friday_common.public import paid_page, webhook_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .credit import rebook_ref
from .events import invoice_lines_payload, publish_invoice_paid
from .models import Customer, Invoice, Payment

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])

# The order a business's connected providers are tried in.
# shortcut: the first connected one wins; let the business choose once one connects several.
PROVIDERS = (
    ("paystack", PaystackProvider, "secret_key"),
    ("stripe", StripeProvider, "secret_key"),
    ("pesapal", PesapalProvider, "consumer_key"),
)
# How the money is booked (Accounting's money accounts).
METHOD = {"paystack": "card", "stripe": "card", "pesapal": "pesapal"}
# When Friday asks again: soon at first, then daily, 30 days in all.
CHECK_AFTER = [timedelta(minutes=m) for m in (10, 30, 60, 180, 360, 720)] + [timedelta(days=1)] * 27


async def provider_for(org_id: str, name: str = ""):
    """(name, client) for the business's connected provider (or the named
    one); None when none is connected."""
    for key, cls, needs in PROVIDERS:
        if name and key != name:
            continue
        config = await get_integration_config(org_id, key)
        if config.get(needs):
            return key, cls(config)
    return None


async def start(session: AsyncSession, org_id: str, inv: Invoice) -> str:
    """Requests the invoice's balance through the business's provider and
    schedules the first check. Returns the provider's name ("" when the
    business has none connected or the customer has no email). The caller
    commits."""
    if inv.kind != "invoice" or inv.status in ("void", "paid", "pending", "draft") or inv.balance_cents <= 0:
        return ""
    customer = await session.get(Customer, inv.customer_id) if inv.customer_id else None
    if customer is None or not customer.email:
        return ""
    found = await provider_for(org_id)
    if found is None:
        return ""
    name, client = found
    await cancel(org_id, inv)
    reference = f"{org_id}:{inv.id}:{secrets.token_hex(4)}"
    due_days = max(0, (inv.due_at - datetime.now(UTC)).days) if inv.due_at else 7
    ipn_url = webhook_url("pesapal")
    metadata = {"org_id": org_id, "invoice_id": str(inv.id), "merchant_reference": reference,
                "callback_url": paid_page(), "ipn_url": ipn_url}
    stored_ipn = await pesapal_ipn_id(session, org_id, client.consumer_key, ipn_url) if name == "pesapal" else ""
    if stored_ipn:
        metadata["ipn_id"] = stored_ipn
    try:
        out = await client.create_pay_request(
            inv.balance_cents, inv.currency, email=customer.email, name=customer.name,
            description=f"Invoice {inv.number}", reference=reference, due_days=due_days,
            metadata=metadata,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(502, f"{name.capitalize()} couldn't take the request: {exc}") from exc
    if name == "pesapal" and not stored_ipn:
        await remember_pesapal_ipn(session, org_id, client.consumer_key, ipn_url, out.get("ipn_id", ""))
    inv.pay_request_provider, inv.pay_request_ref, inv.pay_request_url = name, out["ref"], out["url"]
    inv.pay_request_cents = inv.balance_cents
    await _check_later(session, org_id, inv, 0)
    return name


def _pesapal_account(consumer_key: str) -> str:
    # A new Pesapal account (another consumer key) needs its own IPN id.
    return hashlib.sha256(consumer_key.encode()).hexdigest()[:16]


async def pesapal_ipn_id(session: AsyncSession, org_id: str, consumer_key: str, url: str) -> str:
    """The IPN id Pesapal gave this business for `url` ("" when none is
    stored yet). `session` is scoped to `org_id`."""
    found = await session.scalar(
        text("SELECT ipn_id FROM pesapal_ipns WHERE org_id = :org AND account = :account AND url = :url"),
        {"org": org_id, "account": _pesapal_account(consumer_key), "url": url},
    )
    return found or ""


async def remember_pesapal_ipn(session: AsyncSession, org_id: str, consumer_key: str, url: str, ipn_id: str) -> None:
    """Keeps a newly registered IPN id, so no process registers it again.
    The caller commits."""
    if not ipn_id or not url:
        return
    await session.execute(
        text(
            "INSERT INTO pesapal_ipns (org_id, account, url, ipn_id) VALUES (:org, :account, :url, :ipn)"
            " ON CONFLICT DO NOTHING"
        ),
        {"org": org_id, "account": _pesapal_account(consumer_key), "url": url, "ipn": ipn_id},
    )


async def cancel(org_id: str, inv: Invoice) -> None:
    """Cancels the invoice's open request at its provider (best effort:
    a request already paid is settled by its check)."""
    if not inv.pay_request_ref:
        return
    found = await provider_for(org_id, inv.pay_request_provider)
    if found is not None:
        try:
            await found[1].cancel_pay_request(inv.pay_request_ref)
        except (httpx.HTTPError, RuntimeError) as exc:
            log.warning("cancel %s request %s: %s", inv.pay_request_provider, inv.pay_request_ref, exc)
    inv.pay_request_ref = inv.pay_request_url = ""


async def _check_later(session: AsyncSession, org_id: str, inv: Invoice, attempt: int) -> None:
    if attempt >= len(CHECK_AFTER):
        return
    await publish_event(
        "invoicing.pay_request.check",
        org_id,
        {"invoice_id": str(inv.id), "ref": inv.pay_request_ref, "attempt": attempt},
        session=session,
        deliver_at=datetime.now(UTC) + CHECK_AFTER[attempt],
    )


async def settle(session: AsyncSession, org_id: str, invoice_id: str, ref: str) -> bool:
    """Asks the provider about the invoice's request `ref`; if paid, records
    the payment once. True when it's settled (or there's nothing left to
    ask about). `session` is scoped to `org_id`; this commits."""
    inv = await session.get(Invoice, uuid.UUID(invoice_id), with_for_update=True, populate_existing=True)
    if inv is None or str(inv.org_id) != org_id or inv.pay_request_ref != ref or inv.status == "void":
        return True  # gone, replaced or voided: stop asking
    await session.refresh(inv, attribute_names=["lines", "payments"])
    client_ref = f"request:{inv.pay_request_provider}:{ref}"
    if any(p.client_ref == client_ref for p in inv.payments):
        return True
    found = await provider_for(org_id, inv.pay_request_provider)
    if found is None:
        return True  # disconnected since
    status = await found[1].pay_request_status(ref)
    if not status["paid"]:
        return False
    amount = inv.pay_request_cents if status["amount"] < 0 else status["amount"]
    if amount <= 0 or (status["currency"] and status["currency"] != inv.currency.upper()):
        log.warning("%s request %s paid %s %s; invoice %s not settled", inv.pay_request_provider, ref, amount, status["currency"], inv.number)
        return True
    now = datetime.now(UTC)
    session.add(Payment(org_id=inv.org_id, invoice_id=inv.id, amount_cents=amount,
                        method=METHOD.get(inv.pay_request_provider, "card"), received_at=now, client_ref=client_ref))
    await session.flush()
    await session.refresh(inv, attribute_names=["payments"])
    if inv.paid_cents >= inv.grand_total_cents and inv.status != "paid":
        inv.status, inv.updated_at = "paid", now
        await session.refresh(inv, attribute_names=["lines", "payments"])
        # Saved with the payment, in its transaction (plan 19.2).
        await publish_invoice_paid(org_id, inv, inv.paid_cents, invoice_lines_payload(inv),
                                   posting_ref=rebook_ref(inv, uuid.uuid4().hex), session=session)
    await session.commit()
    return True


@router.post("/pay-request-check", dependencies=[Depends(require_kernel_token)], status_code=204)
async def pay_request_check(body: dict, session: AsyncSession = Depends(get_session)):
    """A scheduled check (invoicing.pay_request.check): settled, or asked
    again later."""
    payload = body.get("payload", {})
    org_id = body["org_id"]
    await set_org_context(session, org_id)
    if not await first_delivery(session, body):
        return
    try:
        done = await settle(session, org_id, payload["invoice_id"], payload.get("ref", ""))
    except (httpx.HTTPError, RuntimeError) as exc:
        log.warning("pay request check %s: %s", payload.get("ref"), exc)
        done = False  # the provider was down: ask again
    if not done:
        inv = await session.get(Invoice, uuid.UUID(payload["invoice_id"]))
        if inv is not None and inv.pay_request_ref == payload.get("ref"):
            await _check_later(session, org_id, inv, int(payload.get("attempt", 0)) + 1)
    await session.commit()
