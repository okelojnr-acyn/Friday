"""The online shop's catalogue (Friday Host STOREFRONT-PLAN.md, Commerce
slice 1). The kernel turns a shop key into a short session (Claims.Via
"shop") for the business and calls these routes; nothing else answers
it. Only what a shopper may see leaves here: name, variant, category,
price, a photo and whether it's in stock. Never cost, quantities,
suppliers or people.

Slice 4: products can be kept off the shop (sell_online), placing an
order holds its stock for a while, and staff move orders along.

Slice 2: quote a basket and place an order. The page sends only product
ids and quantities; prices, totals and what's in stock are worked out
here every time.

An unpaid order holds its stock for HOLD (counted from orders, nothing
to clean up); paying takes the stock off for good (the sale event).
shortcut: pay-on-collection and refunds for a cancelled paid order aren't
here yet; staff use the till and the sale's return for those."""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from friday_common import Principal, get_current_principal, get_org_session, publish_event
from pydantic import BaseModel, Field
from friday_common.access import Scope, require
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductImage, ShopOrder, ShopOrderLine

router = APIRouter(prefix="/shop", tags=["shop"])


async def announce(session: AsyncSession, o: ShopOrder) -> None:
    """Tells the shopper (the kernel emails them, Local "shopmail") when an
    order is placed, paid, ready or cancelled. In the order's transaction."""
    if o.status == "completed" or not o.email:
        return
    await publish_event(
        "inventory.shop_order.updated",
        str(o.org_id),
        {"number": o.number, "status": o.status, "email": o.email, "customer_name": o.customer_name,
         "fulfilment": o.fulfilment, "total_cents": o.total_cents},
        session=session,
    )
staff_router = APIRouter(prefix="/shop_orders", tags=["shop-orders"])

# How long an unpaid order holds its stock.
HOLD = timedelta(hours=2)


def shop_only(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.via != "shop":
        raise HTTPException(403, "this is the online shop's catalogue")
    return principal


@router.get("/catalog")
async def catalog(principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)):
    rows = await session.execute(
        select(Product)
        .where(Product.org_id == uuid.UUID(principal.org_id), Product.price_cents > 0, Product.sell_online)
        .order_by(Product.category, Product.name, Product.variant_name)
    )
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "variant_of": str(p.variant_of) if p.variant_of else None,
            "variant_name": p.variant_name,
            "kind": p.kind,
            "category": p.category,
            "price_cents": p.price_cents,
            "in_stock": (not p.track_inventory) or p.on_hand_qty > 0,
            # The kernel serves it at /public/catalog/products/{id}/image.
            "image_sha": p.image_sha or None,
        }
        for p in rows.scalars()
    ]


@router.get("/products/{product_id}/image")
async def image(
    product_id: uuid.UUID,
    principal: Principal = Depends(shop_only),
    session: AsyncSession = Depends(get_org_session),
):
    product = await session.get(Product, product_id)
    if product is None or str(product.org_id) != principal.org_id or product.price_cents <= 0 or not product.sell_online:
        raise HTTPException(404, "no photo")
    img = await session.get(ProductImage, product_id)
    if img is None:
        raise HTTPException(404, "no photo")
    return Response(content=img.data, media_type=img.content_type)


class BasketLine(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=999)


class Basket(BaseModel):
    lines: list[BasketLine] = Field(min_length=1, max_length=50)


async def _price(session: AsyncSession, principal: Principal, basket: Basket) -> dict:
    """The basket priced from Inventory: each line, the total, and what
    can't be bought (gone, no price, or not enough in stock)."""
    wanted: dict[uuid.UUID, int] = {}
    for line in basket.lines:
        wanted[line.product_id] = wanted.get(line.product_id, 0) + line.quantity
    rows = await session.execute(
        select(Product).where(Product.org_id == uuid.UUID(principal.org_id), Product.id.in_(wanted))
    )
    found = {p.id: p for p in rows.scalars()}
    # Held by other shoppers' unpaid orders placed within HOLD.
    held_rows = await session.execute(
        select(ShopOrderLine.product_id, func.sum(ShopOrderLine.quantity))
        .join(ShopOrder, ShopOrder.id == ShopOrderLine.order_id)
        .where(
            ShopOrder.org_id == uuid.UUID(principal.org_id),
            ShopOrder.status == "placed",
            ShopOrder.created_at > datetime.now(UTC) - HOLD,
            ShopOrderLine.product_id.in_(wanted),
        )
        .group_by(ShopOrderLine.product_id)
    )
    held = {pid: Decimal(n) for pid, n in held_rows}
    lines, problems, total = [], [], 0
    for pid, qty in wanted.items():
        p = found.get(pid)
        if p is None or p.price_cents <= 0 or not p.sell_online:
            problems.append({"product_id": str(pid), "reason": "not for sale"})
            continue
        if qty > 999:
            problems.append({"product_id": str(pid), "reason": "at most 999"})
            continue
        if p.track_inventory and p.on_hand_qty - held.get(pid, Decimal(0)) < qty:
            problems.append({"product_id": str(pid), "reason": "not enough in stock"})
            continue
        line_total = p.price_cents * qty
        total += line_total
        lines.append(
            {
                "product_id": str(pid),
                "name": p.name,
                "variant_name": p.variant_name,
                "unit_price_cents": p.price_cents,
                "quantity": qty,
                "total_cents": line_total,
            }
        )
    return {"lines": lines, "total_cents": total, "problems": problems}


@router.post("/quote")
async def quote(body: Basket, principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)):
    return await _price(session, principal, body)


PHONE = re.compile(r"^\+?[0-9 ]{6,20}$")
EMAIL = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[a-zA-Z]{2,}$")


class OrderIn(Basket):
    customer_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    fulfilment: str = Field(pattern="^(pickup|delivery)$")
    address: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)


def _token_hash(token: str) -> str:
    return hashlib.sha256(("shop-order:" + token).encode()).hexdigest()


def _view(o: ShopOrder) -> dict:
    return {
        "id": str(o.id),
        "number": o.number,
        "status": o.status,
        "fulfilment": o.fulfilment,
        "total_cents": o.total_cents,
        "lines": [
            {"name": li.name, "variant_name": li.variant_name, "unit_price_cents": li.unit_price_cents, "quantity": li.quantity, "total_cents": li.total_cents}
            for li in o.lines
        ],
        "created_at": o.created_at.isoformat(),
    }


@router.post("/orders", status_code=201)
async def place_order(body: OrderIn, principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)):
    phone, email = body.phone.strip(), body.email.strip()
    if not phone and not email:
        raise HTTPException(422, "add a phone number or an email so the shop can reach you")
    if (phone and not PHONE.match(phone)) or (email and not EMAIL.match(email)):
        raise HTTPException(422, "the phone number or email doesn't look right")
    if body.fulfilment == "delivery" and not body.address.strip():
        raise HTTPException(422, "add the delivery address")
    priced = await _price(session, principal, body)
    if priced["problems"]:
        raise HTTPException(409, {"message": "some items can't be ordered", "problems": priced["problems"]})
    org = uuid.UUID(principal.org_id)
    token = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    order = ShopOrder(
        org_id=org,
        # 4 billion numbers per business: a clash is not a real risk.
        number="W" + secrets.token_hex(4).upper(),
        customer_name=body.customer_name.strip(),
        phone=phone,
        email=email,
        fulfilment=body.fulfilment,
        address=body.address.strip(),
        note=body.note.strip(),
        total_cents=priced["total_cents"],
        token_hash=_token_hash(token),
        created_at=now,
        updated_at=now,
        lines=[
            ShopOrderLine(
                org_id=org,
                product_id=uuid.UUID(li["product_id"]),
                name=li["name"],
                variant_name=li["variant_name"],
                unit_price_cents=li["unit_price_cents"],
                quantity=li["quantity"],
                total_cents=li["total_cents"],
            )
            for li in priced["lines"]
        ],
    )
    session.add(order)
    await session.flush()  # sets the id
    view = _view(order)
    await announce(session, order)
    await session.commit()
    # The token is shown once; the shopper keeps it to follow the order.
    return {**view, "token": token}


@router.get("/orders/{order_id}")
async def track_order(
    order_id: uuid.UUID, token: str, principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)
):
    order = await session.get(ShopOrder, order_id)
    if order is None or str(order.org_id) != principal.org_id or not secrets.compare_digest(order.token_hash, _token_hash(token)):
        raise HTTPException(404, "order not found")
    return _view(order)


@router.get("/orders/{order_id}/checkout")
async def order_for_checkout(
    order_id: uuid.UUID, token: str, principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)
):
    """What the kernel needs to take payment: the stored lines (with
    product ids, so the sale takes the stock) and how to reach the buyer."""
    order = await session.get(ShopOrder, order_id)
    if order is None or str(order.org_id) != principal.org_id or not secrets.compare_digest(order.token_hash, _token_hash(token)):
        raise HTTPException(404, "order not found")
    return {
        **_view(order),
        "email": order.email,
        "phone": order.phone,
        "lines": [
            {"product_id": str(li.product_id) if li.product_id else None, "name": li.name, "variant_name": li.variant_name,
             "unit_price_cents": li.unit_price_cents, "quantity": li.quantity}
            for li in order.lines
        ],
    }


# Staff side: the online orders queue (Friday > Inventory > Online orders).
# A paid order is cancelled after its sale is returned (Invoicing's
# /pos/sales/WEB-<number>/return refunds and restocks; the web does both).
NEXT = {"paid": {"ready", "completed", "cancelled"}, "ready": {"completed", "cancelled"}, "placed": {"cancelled"}}


def _staff_view(o: ShopOrder) -> dict:
    view = {**_view(o), "customer_name": o.customer_name, "phone": o.phone, "email": o.email, "address": o.address, "note": o.note}
    # Product ids: taking payment at collection takes the right stock.
    for line, li in zip(view["lines"], o.lines):
        line["product_id"] = str(li.product_id) if li.product_id else None
    return view


@staff_router.get("")
async def list_shop_orders(
    status: str | None = None,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("stock.read")),
    session: AsyncSession = Depends(get_org_session),
):
    query = select(ShopOrder).where(ShopOrder.org_id == uuid.UUID(principal.org_id))
    if status:
        query = query.where(ShopOrder.status == status)
    rows = await session.execute(query.order_by(ShopOrder.created_at.desc()).limit(200))
    return [_staff_view(o) for o in rows.scalars()]


class StatusIn(BaseModel):
    status: str


@staff_router.post("/{order_id}/status")
async def move_shop_order(
    order_id: uuid.UUID,
    body: StatusIn,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("stock.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Paid -> ready -> collected/delivered (completed); an unpaid order can
    be cancelled (its held stock goes back at once), a paid or ready one
    once its sale is returned."""
    order = await session.get(ShopOrder, order_id, with_for_update=True)
    if order is None or str(order.org_id) != principal.org_id:
        raise HTTPException(404, "order not found")
    if body.status not in NEXT.get(order.status, set()):
        raise HTTPException(409, f"a {order.status} order can't become {body.status}")
    order.status = body.status
    order.updated_at = datetime.now(UTC)
    view = _staff_view(order)
    await announce(session, order)
    await session.commit()
    return view
