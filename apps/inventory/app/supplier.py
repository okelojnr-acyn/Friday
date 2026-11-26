"""The supplier page (plan 12.6): a supplier signed in through the
kernel's link and email code (Claims.Via "supplier", subject
"supplier:<id>") sees only their own ordered purchase orders, acknowledges
them, says they're dispatched and adds their invoice. The kernel lets such
a session reach /supplier/* here and nothing else; these routes check the
supplier id themselves too."""

import hashlib
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from friday_common import Principal, get_current_principal, get_org_session
from friday_common.access import Scope, require
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PoInvoiceFile, PurchaseOrder
from .schemas import PurchaseOrderOut

router = APIRouter(prefix="/supplier", tags=["supplier"])

INVOICE_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_INVOICE_BYTES = 2 * 1024 * 1024


def supplier_id(principal: Principal = Depends(get_current_principal)) -> uuid.UUID:
    """The supplier behind this session; anyone else is refused."""
    prefix = "supplier:"
    if principal.via != "supplier" or not principal.user_id.startswith(prefix):
        raise HTTPException(403, "this page is for suppliers")
    try:
        return uuid.UUID(principal.user_id[len(prefix) :])
    except ValueError:
        raise HTTPException(403, "this page is for suppliers") from None


UNSENT = ("draft", "requested", "approved")


async def _their_po(session: AsyncSession, principal: Principal, sid: uuid.UUID, po_id: uuid.UUID) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id)
    # Not sent yet (a draft, or a request to buy): a supplier never sees one.
    if po is None or str(po.org_id) != principal.org_id or po.supplier_id != sid or po.status in UNSENT:
        raise HTTPException(404, "purchase order not found")
    return po


@router.get("/purchase_orders", response_model=list[PurchaseOrderOut])
async def my_purchase_orders(
    principal: Principal = Depends(get_current_principal),
    sid: uuid.UUID = Depends(supplier_id),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.org_id == uuid.UUID(principal.org_id),
            PurchaseOrder.supplier_id == sid,
            PurchaseOrder.status.not_in(UNSENT),
        )
        .order_by(PurchaseOrder.created_at.desc())
    )
    return [PurchaseOrderOut.from_model(po) for po in rows.scalars().all()]


class SupplierUpdate(BaseModel):
    status: str = Field(pattern="^(acknowledged|dispatched)$")
    note: str = Field(default="", max_length=500)


@router.post("/purchase_orders/{po_id}/status", response_model=PurchaseOrderOut)
async def set_supplier_status(
    po_id: uuid.UUID,
    body: SupplierUpdate,
    principal: Principal = Depends(get_current_principal),
    sid: uuid.UUID = Depends(supplier_id),
    session: AsyncSession = Depends(get_org_session),
):
    """Acknowledged, then dispatched (not back again); not once received."""
    po = await _their_po(session, principal, sid, po_id)
    if po.status == "received":
        raise HTTPException(400, "this order was already received")
    if po.supplier_status == "dispatched" and body.status == "acknowledged":
        raise HTTPException(400, "already dispatched")
    now = datetime.now(UTC)
    po.supplier_status = body.status
    po.supplier_note = body.note.strip()
    po.supplier_updated_at = now
    po.updated_at = now
    await session.commit()
    await session.refresh(po)
    return PurchaseOrderOut.from_model(po)


@router.put("/purchase_orders/{po_id}/invoice", response_model=PurchaseOrderOut)
async def put_invoice(
    po_id: uuid.UUID,
    request: Request,
    number: str,
    invoice_date: date,
    principal: Principal = Depends(get_current_principal),
    sid: uuid.UUID = Depends(supplier_id),
    session: AsyncSession = Depends(get_org_session),
):
    """Their invoice: number and date (?number=&invoice_date=) and the file
    as the raw body (PDF or photo, up to 2 MB). Once paid it's fixed."""
    po = await _their_po(session, principal, sid, po_id)
    if po.paid_at is not None:
        raise HTTPException(400, "this order is already paid; ask the business to change its invoice")
    number = number.strip()
    if not number or len(number) > 60:
        raise HTTPException(422, "the invoice number is required (up to 60 characters)")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in INVOICE_TYPES:
        raise HTTPException(415, "send a PDF or a photo (JPEG, PNG, WebP)")
    data = await request.body()
    if not data:
        raise HTTPException(422, "the file is empty")
    if len(data) > MAX_INVOICE_BYTES:
        raise HTTPException(413, "the file is over 2 MB")
    now = datetime.now(UTC)
    file = await session.get(PoInvoiceFile, po.id)
    if file is None:
        session.add(PoInvoiceFile(po_id=po.id, org_id=po.org_id, content_type=content_type, data=data, updated_at=now))
    else:
        file.content_type, file.data, file.updated_at = content_type, data, now
    po.supplier_invoice_no = number
    po.supplier_invoice_date = invoice_date
    po.invoice_file_sha = hashlib.sha256(data).hexdigest()[:16]
    po.supplier_updated_at = now
    po.updated_at = now
    await session.commit()
    await session.refresh(po)
    return PurchaseOrderOut.from_model(po)


async def _invoice_response(session: AsyncSession, po: PurchaseOrder) -> Response:
    file = await session.get(PoInvoiceFile, po.id)
    if file is None:
        raise HTTPException(404, "no invoice file")
    return Response(content=file.data, media_type=file.content_type, headers={"Cache-Control": "private, no-store"})


@router.get("/purchase_orders/{po_id}/invoice")
async def get_my_invoice(
    po_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    sid: uuid.UUID = Depends(supplier_id),
    session: AsyncSession = Depends(get_org_session),
):
    return await _invoice_response(session, await _their_po(session, principal, sid, po_id))


# For the business: the file the supplier added, on the purchase order.
staff_router = APIRouter(prefix="/purchase_orders", tags=["purchase-orders"])


@staff_router.get("/{po_id}/invoice-file")
async def get_invoice_file(
    po_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("purchasing.read")),
    session: AsyncSession = Depends(get_org_session),
):
    po = await session.get(PurchaseOrder, po_id)
    if po is None or str(po.org_id) != principal.org_id:
        raise HTTPException(404, "purchase order not found")
    return await _invoice_response(session, po)
