"""Inbound webhooks from other apps, routed here by the kernel's event
dispatcher (kernel/internal/gateway/events.go). This file is the entire
surface area of Invoicing's coupling to the rest of the system -- it knows
about CRM's event shape, nothing else does.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from friday_common import require_kernel_token, set_org_context
from friday_common.db import get_session

from .models import Customer, Invoice, InvoiceLine

router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


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
        from sqlalchemy import select

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
