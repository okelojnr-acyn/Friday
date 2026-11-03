import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    get_session,
    require_kernel_token,
    resource,
    set_org_context,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    PRODUCT_KINDS,
    PURCHASE_ORDER_STATUSES,
    REASONS,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMove,
    Supplier,
)
from .schemas import (
    ProductBulkCreate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderStatusUpdate,
    StockAdjust,
    StockMoveOut,
    SupplierCreate,
    SupplierOut,
)

resource(
    ResourceSpec(
        name="product",
        app="inventory",
        label="Product",
        label_plural="Products",
        views=("list", "form"),
        search_fields=("name", "sku", "barcode"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("kind", "Kind", "select", options=PRODUCT_KINDS, required=True),
            FieldSpec("sku", "SKU", "text"),
            FieldSpec("barcode", "Barcode", "text"),
            FieldSpec("price_cents", "Price", "currency", required=True),
            FieldSpec("cost_cents", "Cost", "currency"),
            FieldSpec("on_hand_qty", "On hand", "number", form_visible=False),
            FieldSpec("reorder_point", "Reorder at", "number"),
            FieldSpec("track_inventory", "Tracks stock", "boolean"),
        ),
    )
)

resource(
    ResourceSpec(
        name="stock_move",
        app="inventory",
        label="Stock Move",
        label_plural="Stock Moves",
        views=("list",),
        search_fields=("product_name", "reference"),
        fields=(
            FieldSpec("product_name", "Product", "text", required=True),
            FieldSpec("qty_delta", "Change", "number", required=True),
            FieldSpec("reason", "Reason", "select", options=REASONS, required=True),
            FieldSpec("reference", "Reference", "text"),
            FieldSpec("created_at", "When", "datetime"),
        ),
    )
)

resource(
    ResourceSpec(
        name="supplier",
        app="inventory",
        label="Supplier",
        label_plural="Suppliers",
        views=("list", "form"),
        search_fields=("name", "email"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("email", "Email", "email"),
            FieldSpec("phone", "Phone", "phone"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="purchase_order",
        app="inventory",
        label="Purchase Order",
        label_plural="Purchase Orders",
        views=("list", "form"),
        search_fields=("number",),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec("supplier_id", "Supplier", "reference", reference="inventory.supplier", form_visible=False),
            FieldSpec("status", "Status", "select", options=PURCHASE_ORDER_STATUSES, required=True),
            FieldSpec("total_cost_cents", "Total cost", "currency", form_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-inventory")

products_router = APIRouter(prefix="/products", tags=["products"])
moves_router = APIRouter(prefix="/stock_moves", tags=["stock-moves"])
suppliers_router = APIRouter(prefix="/suppliers", tags=["suppliers"])
purchase_orders_router = APIRouter(prefix="/purchase_orders", tags=["purchase-orders"])
webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


@products_router.get("", response_model=list[ProductOut])
async def list_products(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Product).where(Product.org_id == _org(principal)).order_by(Product.name)
    )
    return rows.scalars().all()


def _product_fields(body: ProductCreate) -> dict:
    """Shared by create_product and the bulk endpoint: validates `kind`
    and forces track_inventory=False for a service regardless of what
    the client sent -- a service's on_hand_qty is never meaningful (see
    Product.kind's doc comment), so this isn't optional client-side
    behavior to get right, it's enforced here."""
    if body.kind not in PRODUCT_KINDS:
        raise HTTPException(422, f"kind must be one of {PRODUCT_KINDS}")
    data = body.model_dump()
    if body.kind == "service":
        data["track_inventory"] = False
    return data


@products_router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    body: ProductCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    now = datetime.now(UTC)
    product = Product(org_id=_org(principal), created_at=now, updated_at=now, **_product_fields(body))
    session.add(product)
    await session.flush()
    if product.on_hand_qty:
        session.add(
            StockMove(
                org_id=_org(principal),
                product_id=product.id,
                product_name=product.name,
                qty_delta=product.on_hand_qty,
                reason="received",
                reference="initial stock",
                created_at=now,
            )
        )
    await session.commit()
    await session.refresh(product)
    return product


async def _get_owned(session: AsyncSession, principal: Principal, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if product is None or str(product.org_id) != principal.org_id:
        raise HTTPException(404, "product not found")
    return product


@products_router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_owned(session, principal, product_id)


@products_router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    product = await _get_owned(session, principal, product_id)
    changes = body.model_dump(exclude_unset=True)
    if "kind" in changes and changes["kind"] not in PRODUCT_KINDS:
        raise HTTPException(422, f"kind must be one of {PRODUCT_KINDS}")
    for field_name, value in changes.items():
        setattr(product, field_name, value)
    if product.kind == "service":
        product.track_inventory = False
    product.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(product)
    return product


@products_router.post("/bulk", response_model=list[ProductOut], status_code=201)
async def bulk_create_products(
    body: ProductBulkCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The bulk-add screen's one call (see web/src/apps/inventory/
    BulkAddProductsPanel.tsx): scan/type a batch of products or
    services and create them all in one request instead of one
    round trip per row."""
    now = datetime.now(UTC)
    created: list[Product] = []
    for item in body.products:
        product = Product(org_id=_org(principal), created_at=now, updated_at=now, **_product_fields(item))
        session.add(product)
        created.append(product)
    await session.flush()
    for product in created:
        if product.on_hand_qty:
            session.add(
                StockMove(
                    org_id=_org(principal),
                    product_id=product.id,
                    product_name=product.name,
                    qty_delta=product.on_hand_qty,
                    reason="received",
                    reference="bulk add",
                    created_at=now,
                )
            )
    await session.commit()
    for product in created:
        await session.refresh(product)
    return created


@products_router.post("/{product_id}/adjust-stock", response_model=ProductOut)
async def adjust_stock(
    product_id: uuid.UUID,
    body: StockAdjust,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The one way on_hand_qty ever changes by hand -- always alongside a
    StockMove row, so the ledger and the cached count never drift apart."""
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {REASONS}")
    product = await _get_owned(session, principal, product_id)
    now = datetime.now(UTC)
    product.on_hand_qty += body.delta
    product.updated_at = now
    session.add(
        StockMove(
            org_id=_org(principal),
            product_id=product.id,
            product_name=product.name,
            qty_delta=body.delta,
            reason=body.reason,
            reference=body.reference,
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(product)
    return product


@moves_router.get("", response_model=list[StockMoveOut])
async def list_stock_moves(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(StockMove).where(StockMove.org_id == _org(principal)).order_by(StockMove.created_at.desc())
    )
    return rows.scalars().all()


@webhooks_router.post("/pos-sale", dependencies=[Depends(require_kernel_token)], status_code=204)
async def pos_sale_recorded(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to invoicing.pos_sale.recorded (see
    kernel/internal/gateway/events.go) -- automatically decrements stock
    for every sold line that was rung up from the product catalog
    (freeform/ad-hoc POS lines carry no product_id and are skipped)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    now = datetime.now(UTC)

    for line in payload.get("lines", []):
        product_id = line.get("product_id")
        if not product_id:
            continue
        product = await session.get(Product, uuid.UUID(product_id))
        if product is None or str(product.org_id) != str(org_id) or not product.track_inventory:
            continue
        qty = int(line.get("quantity", 0))
        product.on_hand_qty -= qty
        product.updated_at = now
        session.add(
            StockMove(
                org_id=org_id,
                product_id=product.id,
                product_name=product.name,
                qty_delta=-qty,
                reason="pos_sale",
                reference=payload.get("invoice_number", ""),
                created_at=now,
            )
        )
    await session.commit()


@suppliers_router.get("", response_model=list[SupplierOut])
async def list_suppliers(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Supplier).where(Supplier.org_id == _org(principal)).order_by(Supplier.name)
    )
    return rows.scalars().all()


@suppliers_router.post("", response_model=SupplierOut, status_code=201)
async def create_supplier(
    body: SupplierCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    supplier = Supplier(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(supplier)
    await session.commit()
    await session.refresh(supplier)
    return supplier


async def _get_owned_po(session: AsyncSession, principal: Principal, po_id: uuid.UUID) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id)
    if po is None or str(po.org_id) != principal.org_id:
        raise HTTPException(404, "purchase order not found")
    return po


@purchase_orders_router.get("", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.org_id == _org(principal)).order_by(PurchaseOrder.created_at.desc())
    )
    return [PurchaseOrderOut.from_model(po) for po in rows.scalars().all()]


@purchase_orders_router.post("", response_model=PurchaseOrderOut, status_code=201)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    now = datetime.now(UTC)
    po = PurchaseOrder(
        org_id=_org(principal),
        supplier_id=body.supplier_id,
        number=f"PO-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(po)
    await session.flush()
    for line in body.lines:
        session.add(
            PurchaseOrderLine(
                org_id=_org(principal),
                purchase_order_id=po.id,
                product_id=line.product_id,
                description=line.description,
                quantity=line.quantity,
                unit_cost_cents=line.unit_cost_cents,
            )
        )
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.get("/{po_id}", response_model=PurchaseOrderOut)
async def get_purchase_order(
    po_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    po = await _get_owned_po(session, principal, po_id)
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.patch("/{po_id}/status", response_model=PurchaseOrderOut)
async def set_purchase_order_status(
    po_id: uuid.UUID,
    body: PurchaseOrderStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in PURCHASE_ORDER_STATUSES:
        raise HTTPException(422, f"status must be one of {PURCHASE_ORDER_STATUSES}")
    po = await _get_owned_po(session, principal, po_id)
    previous_status = po.status
    po.status = body.status
    po.updated_at = datetime.now(UTC)

    # Receiving a PO is the one side effect: each line carrying a
    # product_id bumps that product's on_hand_qty and writes a StockMove,
    # the same ledger-plus-cache shape adjust_stock and pos_sale_recorded
    # already use. Only fires on the transition into "received" so
    # re-saving an already-received PO never double-counts stock.
    if previous_status != "received" and body.status == "received":
        for line in po.lines:
            if not line.product_id:
                continue
            product = await session.get(Product, line.product_id)
            if product is None or str(product.org_id) != principal.org_id or not product.track_inventory:
                continue
            product.on_hand_qty += line.quantity
            product.updated_at = po.updated_at
            session.add(
                StockMove(
                    org_id=_org(principal),
                    product_id=product.id,
                    product_name=product.name,
                    qty_delta=line.quantity,
                    reason="received",
                    reference=po.number,
                    created_at=po.updated_at,
                )
            )

    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.post("/from-product/{product_id}", response_model=PurchaseOrderOut, status_code=201)
async def create_purchase_order_from_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The "Create purchase order" action on a low-stock product (see
    web/src/apps/inventory/CreatePurchaseOrderPanel.tsx) -- a one-line
    draft PO that restocks to double the reorder point, left in "draft"
    for a human to pick a supplier and actually send."""
    product = await _get_owned(session, principal, product_id)
    now = datetime.now(UTC)
    quantity = max(product.reorder_point * 2 - product.on_hand_qty, 1)
    po = PurchaseOrder(
        org_id=_org(principal),
        number=f"PO-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderLine(
            org_id=_org(principal),
            purchase_order_id=po.id,
            product_id=product.id,
            description=product.name,
            quantity=quantity,
            unit_cost_cents=product.cost_cents,
        )
    )
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return PurchaseOrderOut.from_model(po)


app.include_router(products_router)
app.include_router(moves_router)
app.include_router(suppliers_router)
app.include_router(purchase_orders_router)
app.include_router(webhooks_router)
