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
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from friday_common import get_integration_config, require_kernel_token, set_org_context
from friday_common.db import get_session
from friday_common.integrations import PesapalProvider, StripeProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .events import invoice_lines_payload, publish_invoice_paid, publish_pos_sale_recorded
from .models import Customer, Invoice, InvoiceLine, Payment

router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])
external_router = APIRouter(prefix="/external/webhooks", tags=["external-webhooks"])


@router.post("/crm-won", dependencies=[Depends(require_kernel_token)], status_code=201)
async def crm_opportunity_won(body: dict, session: AsyncSession = Depends(get_session)):
    event_payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    now = datetime.now(UTC)
    await set_org_context(session, str(org_id))

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
        raise HTTPException(400, "missing invoice metadata")

    config = await get_integration_config(org_id, "stripe")
    if not config.get("secret_key"):
        raise HTTPException(400, "stripe not configured for this org")

    sig_header = request.headers.get("stripe-signature", "")
    if not StripeProvider(config).verify_webhook_signature(raw_body, sig_header):
        raise HTTPException(400, "invalid signature")

    if event.get("type") != "payment_intent.succeeded":
        return {"ignored": event.get("type")}

    await set_org_context(session, org_id)
    inv = await session.get(Invoice, uuid.UUID(invoice_id))
    if inv is None or str(inv.org_id) != org_id:
        raise HTTPException(404, "invoice not found")

    await session.refresh(inv, attribute_names=["lines", "payments"])
    total = inv.grand_total_cents  # incl. tax -- see Invoice.grand_total_cents
    already_paid = inv.paid_cents
    amount = payment_intent.get("amount_received", total - already_paid)
    now = datetime.now(UTC)

    session.add(
        Payment(org_id=uuid.UUID(org_id), invoice_id=inv.id, amount_cents=amount, method="card", received_at=now)
    )
    await session.flush()
    await session.refresh(inv, attribute_names=["payments"])
    paid = sum(p.amount_cents for p in inv.payments)
    newly_paid = paid >= total and inv.status not in ("paid", "void")
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = now

    await session.commit()
    if newly_paid:
        await session.refresh(inv, attribute_names=["lines", "payments"])
        await publish_invoice_paid(org_id, inv, paid, invoice_lines_payload(inv))
    return {"ok": True}


@external_router.get("/pesapal")
async def pesapal_webhook(
    order_tracking_id: str = Query(alias="OrderTrackingId"),
    order_merchant_reference: str = Query(alias="OrderMerchantReference"),
    session: AsyncSession = Depends(get_session),
):
    """Pesapal calls this directly (registered once per process via
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
    parsed."""
    try:
        org_id, invoice_id = order_merchant_reference.split(":", 1)
    except ValueError:
        raise HTTPException(400, "malformed merchant reference")

    config = await get_integration_config(org_id, "pesapal")
    if not config.get("consumer_key"):
        raise HTTPException(400, "pesapal not configured for this org")

    await set_org_context(session, org_id)
    invoice = await session.get(Invoice, uuid.UUID(invoice_id))
    if invoice is None or str(invoice.org_id) != org_id:
        raise HTTPException(404, "invoice not found")
    if invoice.status != "pending":
        return {"ok": True}  # already resolved -- IPN delivery can repeat

    status = await PesapalProvider(config).get_transaction_status(order_tracking_id)
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
        await session.commit()
        await session.refresh(invoice, attribute_names=["lines", "payments"])
        await publish_pos_sale_recorded(org_id, invoice, charged_cents)
        await publish_invoice_paid(org_id, invoice, charged_cents, invoice_lines_payload(invoice))
    elif status in ("FAILED", "INVALID"):
        invoice.status = "void"
        invoice.updated_at = now
        await session.commit()
    # else ("PENDING", "REVERSED", or anything unrecognized): leave as
    # "pending" -- Pesapal may call the IPN again as the status changes.

    return {"ok": True}
