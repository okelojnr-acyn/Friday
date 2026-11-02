import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    publish_event,
    resource,
)

from .models import INVOICE_STATUSES, Customer, Invoice, InvoiceLine, Payment
from .schemas import (
    CustomerCreate,
    CustomerOut,
    InvoiceCreate,
    InvoiceOut,
    InvoiceStatusUpdate,
    PaymentCreate,
)
from .webhooks import router as webhooks_router

resource(
    ResourceSpec(
        name="customer",
        app="invoicing",
        label="Customer",
        label_plural="Customers",
        views=("list", "form"),
        search_fields=("name", "company", "email"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("company", "Company", "text"),
            FieldSpec("email", "Email", "email"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="invoice",
        app="invoicing",
        label="Invoice",
        label_plural="Invoices",
        views=("list", "form"),
        search_fields=("number",),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec(
                "customer_id",
                "Customer",
                "reference",
                reference="invoicing.customer",
                form_visible=False,
            ),
            FieldSpec("status", "Status", "select", options=INVOICE_STATUSES, required=True),
            FieldSpec("total_cents", "Total", "currency", form_visible=False),
            FieldSpec("balance_cents", "Balance", "currency", form_visible=False),
            FieldSpec("source", "Source", "select", options=("manual", "crm", "pos"), form_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-invoicing")

customers_router = APIRouter(prefix="/customers", tags=["customers"])
invoices_router = APIRouter(prefix="/invoices", tags=["invoices"])
pos_router = APIRouter(prefix="/pos", tags=["pos-sync"])


@customers_router.get("", response_model=list[CustomerOut])
async def list_customers(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Customer).where(Customer.org_id == uuid.UUID(principal.org_id)).order_by(Customer.created_at.desc())
    )
    return rows.scalars().all()


@customers_router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    body: CustomerCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    customer = Customer(org_id=uuid.UUID(principal.org_id), created_at=datetime.now(UTC), **body.model_dump())
    session.add(customer)
    await session.commit()
    await session.refresh(customer)
    return customer


async def _get_invoice(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    inv = await session.get(Invoice, invoice_id)
    if inv is None or str(inv.org_id) != principal.org_id:
        raise HTTPException(404, "invoice not found")
    return inv


@invoices_router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Invoice).where(Invoice.org_id == uuid.UUID(principal.org_id)).order_by(Invoice.created_at.desc())
    )
    return [InvoiceOut.from_model(inv) for inv in rows.scalars().all()]


@invoices_router.post("", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    now = datetime.now(UTC)
    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        customer_id=body.customer_id,
        number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=body.currency,
        source="manual",
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()
    for line in body.lines:
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description=line.description,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
            )
        )
    await session.commit()
    await session.refresh(invoice, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(invoice)


@invoices_router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    inv = await _get_invoice(session, principal, invoice_id)
    return InvoiceOut.from_model(inv)


@invoices_router.patch("/{invoice_id}/status", response_model=InvoiceOut)
async def set_invoice_status(
    invoice_id: uuid.UUID,
    body: InvoiceStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in INVOICE_STATUSES:
        raise HTTPException(422, f"status must be one of {INVOICE_STATUSES}")
    inv = await _get_invoice(session, principal, invoice_id)
    inv.status = body.status
    inv.updated_at = datetime.now(UTC)
    if body.status == "sent" and inv.issued_at is None:
        inv.issued_at = inv.updated_at
    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(inv)


@invoices_router.post("/{invoice_id}/payments", response_model=InvoiceOut, status_code=201)
async def record_payment(
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    inv = await _get_invoice(session, principal, invoice_id)
    session.add(
        Payment(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=inv.id,
            amount_cents=body.amount_cents,
            method=body.method,
            received_at=datetime.now(UTC),
        )
    )
    await session.flush()
    await session.refresh(inv, attribute_names=["lines", "payments"])

    total = sum(l.total_cents for l in inv.lines)
    paid = sum(p.amount_cents for p in inv.payments)
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(inv)


@pos_router.post("/sales", status_code=201)
async def record_pos_sale(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Where the Rust POS engine's offline sync queue lands once a device
    is back online. A POS sale becomes an already-paid invoice with
    source='pos' -- same ledger, no separate "sales" table to reconcile
    against invoicing later."""
    now = datetime.now(UTC)
    lines_in = body.get("lines", [])
    if not lines_in:
        raise HTTPException(422, "sale must have at least one line")

    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"POS-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="paid",
        currency=body.get("currency", "USD"),
        source="pos",
        source_ref=body.get("client_sale_id"),
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()

    total_cents = 0
    for line in lines_in:
        qty = line.get("quantity", 1)
        unit_price = line.get("unit_price_cents", 0)
        total_cents += int(qty * unit_price)
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description=line.get("description", "Item"),
                quantity=qty,
                unit_price_cents=unit_price,
            )
        )

    # pos-engine's Cart.total_cents() (what the register actually charged,
    # body["amount_cents"]) includes tax; the line items above don't carry
    # a tax line of their own. Without reconciling the two, total_cents
    # (sum of lines) undercounts what was paid and the invoice shows a
    # negative balance on every taxed sale. Record the difference as its
    # own line so the invoice ledger and the amount collected always agree.
    charged_cents = body.get("amount_cents", total_cents)
    tax_cents = charged_cents - total_cents
    if tax_cents > 0:
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description="Tax",
                quantity=1,
                unit_price_cents=tax_cents,
            )
        )
        total_cents = charged_cents

    session.add(
        Payment(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=invoice.id,
            amount_cents=charged_cents,
            method=body.get("method", "pos"),
            received_at=now,
        )
    )
    await session.commit()
    await session.refresh(invoice, attribute_names=["lines", "payments"])

    # Lets Inventory auto-decrement stock for any line rung up from the
    # product catalog (product_id set client-side by the POS register --
    # see web/src/apps/pos/PosPage.tsx). Freeform/ad-hoc lines have no
    # product_id and are skipped on the subscriber side.
    await publish_event(
        "invoicing.pos_sale.recorded",
        principal.org_id,
        {
            "invoice_number": invoice.number,
            "lines": [
                {
                    "product_id": line.get("product_id"),
                    "quantity": line.get("quantity", 1),
                }
                for line in lines_in
                if line.get("product_id")
            ],
        },
    )

    return InvoiceOut.from_model(invoice)


app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(pos_router)
app.include_router(webhooks_router)
