"""Inbound webhooks. Two different trust models live in this one file:

- `router` (`/internal/webhooks/*`): from other Friday apps, routed here
  by the kernel's event dispatcher (kernel/internal/gateway/events.go)
  and gated by the shared kernel token. This is the surface area of
  Invoicing's coupling to the rest of the system -- it knows about CRM's
  event shape, nothing else does.
- `external_router` (`/external/webhooks/*`): from the public internet
  (Stripe, Pesapal), which can't carry a Friday JWT or the kernel token.
  See `stripe_webhook`'s and `pesapal_webhook`'s own doc comments for the
  (different) trust models each uses instead, and
  INTEGRATIONS.md#stripe/#pesapal for the deployment-level routing this
  needs (the kernel's gateway requires auth on every `/api/{app}/*`
  route, so exposing this path means routing it to the invoicing service
  directly, bypassing the kernel for this one path).
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from friday_common import first_delivery, get_integration_config, require_kernel_token, set_org_context
from friday_common.db import get_session
from friday_common.integrations import PaystackProvider, PesapalProvider, StripeProvider
from friday_common.integrations.config import forwarding_configs
from friday_common.public import forward_in_background, forward_targets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .events import invoice_lines_payload, publish_invoice_paid, publish_pos_sale_recorded
from .models import Customer, Invoice, InvoiceLine, Payment
from .paystack_pay import parse_debt_reference, parse_reference, settle_debt
from .paystack_pay import settle as settle_paystack

from .pay_requests import settle as settle_pay_request

router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])
external_router = APIRouter(prefix="/external/webhooks", tags=["external-webhooks"])
log = logging.getLogger(__name__)


@router.post("/crm-won", dependencies=[Depends(require_kernel_token)], status_code=201)
async def crm_opportunity_won(body: dict, session: AsyncSession = Depends(get_session)):
    event_payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    now = datetime.now(UTC)
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return

    # Match an existing customer by email within this org, or create one.
    customer = None
    email = event_payload.get("contact_email") or ""
    if email:
        existing = await session.execute(
            select(Customer).where(Customer.org_id == org_id, Customer.email == email)
        )
        customer = existing.scalars().first()

    if customer is None:
        customer = Customer(
            org_id=org_id,
            name=event_payload.get("contact_name", "Unknown"),
            email=email,
            company=event_payload.get("company", ""),
            created_at=now,
        )
        session.add(customer)
        await session.flush()

    invoice = Invoice(
        org_id=org_id,
        customer_id=customer.id,
        number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=event_payload.get("currency", "USD"),
        source="crm",
        source_ref=event_payload.get("opportunity_id"),
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()

    session.add(
        InvoiceLine(
            org_id=org_id,
            invoice_id=invoice.id,
            description=f"Won opportunity: {event_payload.get('company') or event_payload.get('contact_name', '')}",
            quantity=1,
            unit_price_cents=event_payload.get("value_cents", 0),
        )
    )
    await session.commit()
    return {"invoice_id": str(invoice.id), "number": invoice.number}


@external_router.post("/stripe")
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """Stripe calls this directly -- there's no Friday JWT or kernel
    token to check, so the trust model is different from every other
    webhook in this file: verify Stripe's own signature before trusting
    anything in the body, not after.

    The chicken-and-egg problem: verifying the signature needs this org's
    `webhook_secret`, but nothing identifies the org until the body is
    parsed. Resolved by having `pay_with_card` (main.py) put `org_id` in
    the PaymentIntent's own metadata when it's created -- that id is only
    ever used to pick *which* org's secret to check the signature
    against, never trusted before the signature check passes. A forged
    org_id just means checking against the wrong org's secret (or none),
    which fails the signature check exactly like tampering would.
    """
    raw_body = await request.body()
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid payload")

    payment_intent = event.get("data", {}).get("object", {})
    metadata = payment_intent.get("metadata", {})
    org_id = metadata.get("org_id")
    invoice_id = metadata.get("invoice_id")
    if not org_id or not invoice_id:
        # Not one of Friday's (a Stripe Invoice's own payment intent, say):
        # acknowledged, so Stripe doesn't keep retrying it; nothing is done.
        return {"ignored": "not a Friday payment"}

    config = await get_integration_config(org_id, "stripe")
    if not config.get("secret_key"):
        raise HTTPException(400, "stripe not configured for this org")

    sig_header = request.headers.get("stripe-signature", "")
    if not StripeProvider(config).verify_webhook_signature(raw_body, sig_header):
        raise HTTPException(400, "invalid signature")

    if event.get("type") == "invoice.paid":
        # A pay request (Stripe Invoice): settled by asking Stripe, as the
        # scheduled check would, only sooner.
        await set_org_context(session, org_id)
        await settle_pay_request(session, org_id, invoice_id, str(payment_intent.get("id") or ""))
        return {"ok": True}
    if event.get("type") != "payment_intent.succeeded":
        return {"ignored": event.get("type")}

    await set_org_context(session, org_id)
    # Locked so two deliveries of one event (Stripe retries) can't both record it.
    inv = await session.get(Invoice, uuid.UUID(invoice_id), with_for_update=True, populate_existing=True)
    if inv is None or str(inv.org_id) != org_id:
        raise HTTPException(404, "invoice not found")

    await session.refresh(inv, attribute_names=["lines", "payments"])
    # One payment per PaymentIntent, however often Stripe delivers it.
    client_ref = f"stripe:{payment_intent.get('id') or ''}"
    if client_ref == "stripe:":
        raise HTTPException(400, "payment intent has no id")
    if any(p.client_ref == client_ref for p in inv.payments):
        await session.commit()
        return {"ok": True}
    total = inv.grand_total_cents  # incl. tax -- see Invoice.grand_total_cents
    already_paid = inv.paid_cents
    amount = payment_intent.get("amount_received", total - already_paid)
    now = datetime.now(UTC)

    session.add(
        Payment(
            org_id=uuid.UUID(org_id),
            invoice_id=inv.id,
            amount_cents=amount,
            method="card",
            received_at=now,
            client_ref=client_ref,
        )
    )
    await session.flush()
    await session.refresh(inv, attribute_names=["payments"])
    paid = sum(p.amount_cents for p in inv.payments)
    newly_paid = paid >= total and inv.status not in ("paid", "void")
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = now

    if newly_paid:
        # Saved with the payment, in its transaction (plan 19.2).
        await session.flush()
        await session.refresh(inv, attribute_names=["lines", "payments"])
        await publish_invoice_paid(org_id, inv, paid, invoice_lines_payload(inv), session=session)
    await session.commit()
    return {"ok": True}


@external_router.get("/pesapal")
async def pesapal_webhook(
    order_tracking_id: str = Query(alias="OrderTrackingId"),
    order_merchant_reference: str = Query(alias="OrderMerchantReference"),
    order_notification_type: str = Query("IPNCHANGE", alias="OrderNotificationType"),
    session: AsyncSession = Depends(get_session),
):
    """Pesapal calls this directly (registered once per business via
    PesapalProvider's RegisterIPN, see pay_with_pesapal in main.py) --
    same "no Friday JWT or kernel token" trust model as stripe_webhook,
    but Pesapal's version of "don't trust the callback" is stronger: the
    query params here are used only to know *which* order to re-query,
    never as the actual payment status. The real status always comes
    from a fresh GetTransactionStatus call using the opaque
    order_tracking_id Pesapal itself issued.

    org_id rides along in order_merchant_reference ("{org_id}:{invoice_id}",
    set by pay_with_pesapal) for the same chicken-and-egg reason
    stripe_webhook's PaymentIntent metadata carries org_id: nothing
    identifies which org's config to check until the reference is
    parsed.

    Answers with the acknowledgement Pesapal documents (its IPN section:
    the notification's own fields echoed back with "status": 200), so it
    stops re-sending."""
    ack = {
        "orderNotificationType": order_notification_type,
        "orderTrackingId": order_tracking_id,
        "orderMerchantReference": order_merchant_reference,
        "status": 200,
    }
    # "{org_id}:{invoice_id}" from the till; a pay request adds ":<random>".
    parts = order_merchant_reference.split(":")
    if len(parts) not in (2, 3):
        raise HTTPException(400, "malformed merchant reference")
    org_id, invoice_id = parts[0], parts[1]
    if len(parts) == 3:
        config = await get_integration_config(org_id, "pesapal")
        if not config.get("consumer_key"):
            raise HTTPException(400, "pesapal not configured for this org")
        await set_org_context(session, org_id)
        await settle_pay_request(session, org_id, invoice_id, order_tracking_id)
        return ack

    config = await get_integration_config(org_id, "pesapal")
    if not config.get("consumer_key"):
        raise HTTPException(400, "pesapal not configured for this org")

    await set_org_context(session, org_id)
    invoice = await session.get(Invoice, uuid.UUID(invoice_id))
    if invoice is None or str(invoice.org_id) != org_id:
        raise HTTPException(404, "invoice not found")
    await settle_pesapal_sale(session, org_id, invoice, order_tracking_id, config)
    return ack


async def settle_pesapal_sale(session: AsyncSession, org_id: str, invoice: Invoice, tracking_id: str, config: dict) -> None:
    """Asks Pesapal about a till sale's order and records the result once
    (the IPN and the till's status poll both end here). `session` is
    scoped to `org_id`; this commits when it changes anything."""
    if invoice.status != "pending":
        return  # already resolved -- IPN delivery can repeat
    if invoice.pesapal_tracking_id and invoice.pesapal_tracking_id != tracking_id:
        log.warning("pesapal %s is not the order sale %s waits on", tracking_id, invoice.number)
        return

    status = await PesapalProvider(config).get_transaction_status(tracking_id)
    # Locked, and checked again: two IPNs (or an IPN and a poll) in flight
    # must not both record the payment.
    invoice = await session.get(Invoice, invoice.id, with_for_update=True, populate_existing=True)
    if invoice is None or invoice.status != "pending":
        await session.commit()
        return
    now = datetime.now(UTC)

    if status == "COMPLETED":
        await session.refresh(invoice, attribute_names=["lines"])
        # The reconciling Tax/Discount line _apply_pos_sale_lines (main.py)
        # already added makes this sum exactly equal the amount Pesapal
        # actually collected -- same invariant record_pos_sale relies on.
        charged_cents = sum(line.total_cents for line in invoice.lines)
        session.add(
            Payment(
                org_id=uuid.UUID(org_id),
                invoice_id=invoice.id,
                amount_cents=charged_cents,
                method="pesapal",
                received_at=now,
            )
        )
        invoice.status = "paid"
        invoice.updated_at = now
        await session.flush()
        await session.refresh(invoice, attribute_names=["lines", "payments"])
        await publish_pos_sale_recorded(org_id, invoice, charged_cents, session=session)
        await publish_invoice_paid(org_id, invoice, charged_cents, invoice_lines_payload(invoice), session=session)
        await session.commit()
    elif status in ("FAILED", "INVALID"):
        invoice.status = "void"
        invoice.updated_at = now
        await session.commit()
    else:
        # "PENDING", "REVERSED", or anything unrecognized: left "pending" --
        # Pesapal may call the IPN again as the status changes.
        await session.commit()


@external_router.post("/paystack")
async def paystack_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """The business's Paystack calls this (the URL is set in their Paystack
    dashboard). The reference ("<org>.<invoice>.<random>", from
    paystack_pay.new_reference) only says which org's key checks the
    `x-paystack-signature` and which invoice to settle; settle then asks
    Paystack itself. The body's own status and amount are never used.

    A Payment Request (pay_requests.py) has no Friday reference; its
    `paymentrequest.success` carries the org and invoice in the metadata
    Friday sent, and settles the invoice's request at once (the scheduled
    checks stay as the fallback and stop once it's paid)."""
    raw_body = await request.body()
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid payload")
    data = event.get("data") or {}
    signature = request.headers.get("x-paystack-signature", "")
    reference = str(data.get("reference") or "")
    parsed = parse_reference(reference)
    debt = parse_debt_reference(reference)
    pay_request = _pay_request_target(event) if parsed is None and debt is None else None
    if parsed is None and debt is None and pay_request is None:
        await _forward_foreign_paystack(raw_body, signature)
        return {"ignored": "not a Friday reference"}
    org_id = (parsed or debt or pay_request)[0]

    config = await get_integration_config(org_id, "paystack")
    if not config.get("secret_key"):
        # 200, not an error: a 400 has Paystack retry it for 72 hours for nothing.
        return {"ignored": "paystack not connected for this business"}
    if not PaystackProvider(config).verify_webhook_signature(raw_body, signature):
        raise HTTPException(400, "invalid signature")
    if pay_request is not None:
        await set_org_context(session, org_id)
        await settle_pay_request(session, org_id, pay_request[1], pay_request[2])
        return {"ok": True}
    if event.get("event") != "charge.success":
        return {"ignored": event.get("event")}

    await set_org_context(session, org_id)
    if parsed:
        await settle_paystack(session, org_id, parsed[1], reference)
    else:
        await settle_debt(session, org_id, debt[1], reference)
    return {"ok": True}


def _pay_request_target(event: dict) -> tuple[str, str, str] | None:
    """(org, invoice, request_code) of a `paymentrequest.success` Friday
    asked for, from the metadata pay_requests.start sent; None otherwise.
    The org only picks which key checks the signature."""
    if event.get("event") != "paymentrequest.success":
        return None
    data = event.get("data") or {}
    meta = data.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return None
    if not isinstance(meta, dict) or not data.get("request_code"):
        return None
    try:
        org_id, invoice_id = str(uuid.UUID(str(meta.get("org_id")))), str(uuid.UUID(str(meta.get("invoice_id"))))
    except ValueError:
        return None
    return org_id, invoice_id, str(data["request_code"])


async def _forward_foreign_paystack(raw_body: bytes, signature: str) -> None:
    """Paystack allows one webhook URL per account. A business whose account
    also serves another system (its website) lists that system under
    "Also send these events to"; an event that isn't Friday's goes there,
    but only after it checks out against that business's own secret key, so
    nothing unattributed is ever passed on."""
    if not signature:
        return
    for item in await forwarding_configs("paystack"):
        config = item.get("config") or {}
        if config.get("secret_key") and PaystackProvider(config).verify_webhook_signature(raw_body, signature):
            forward_in_background(
                forward_targets(config),
                "POST",
                raw_body,
                {"content-type": "application/json", "x-paystack-signature": signature},
            )
            return
