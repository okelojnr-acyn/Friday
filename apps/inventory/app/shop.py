"""The online shop's catalogue (Friday Host STOREFRONT-PLAN.md, Commerce
slice 1). The kernel turns a shop key into a short session (Claims.Via
"shop") for the business and calls these routes; nothing else answers
it. Only what a shopper may see leaves here: name, variant, category,
price, a photo and whether it's in stock. Never cost, quantities,
suppliers or people.

shortcut: every product with a price is listed; a per-product "sell
online" switch comes with the staff side of online orders (slice 4)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from friday_common import Principal, get_current_principal, get_org_session
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductImage

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
