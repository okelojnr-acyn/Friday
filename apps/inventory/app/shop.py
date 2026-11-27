"""The online shop's catalogue (Friday Host STOREFRONT-PLAN.md, Commerce
slice 1). The kernel turns a shop key into a short session (Claims.Via
"shop") for the business and calls these routes; nothing else answers
it. Only what a shopper may see leaves here: name, variant, category,
price, a photo and whether it's in stock. Never cost, quantities,
suppliers or people.

shortcut: every product with a price is listed; a per-product "sell
online" switch comes with the staff side of online orders (slice 4).

Slice 2: quote a basket and place an order. The page sends only product
ids and quantities; prices, totals and what's in stock are worked out
here every time.

shortcut: placing an order doesn't hold stock; two shoppers can order the
last item until payment (slice 3) or staff (slice 4) take it off."""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from friday_common import Principal, get_current_principal, get_org_session
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductImage, ShopOrder, ShopOrderLine

router = APIRouter(prefix="/shop", tags=["shop"])


def shop_only(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.via != "shop":
        raise HTTPException(403, "this is the online shop's catalogue")
    return principal


@router.get("/catalog")
async def catalog(principal: Principal = Depends(shop_only), session: AsyncSession = Depends(get_org_session)):
    rows = await session.execute(
        select(Product)
        .where(Product.org_id == uuid.UUID(principal.org_id), Product.price_cents > 0)
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
    if product is None or str(product.org_id) != principal.org_id or product.price_cents <= 0:
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
    lines, problems, total = [], [], 0
    for pid, qty in wanted.items():
        p = found.get(pid)
        if p is None or p.price_cents <= 0:
            problems.append({"product_id": str(pid), "reason": "not for sale"})
            continue
        if qty > 999:
            problems.append({"product_id": str(pid), "reason": "at most 999"})
            continue
        if p.track_inventory and p.on_hand_qty < qty:
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
