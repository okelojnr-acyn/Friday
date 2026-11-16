"""Registering products with KRA eTIMS (/saveItem). eTIMS only accepts a
sale of an item it knows, so each product is registered once before its
first automated sale. Gated like the sales sender: refused until the
server runs with ETIMS_AUTOMATION=1 (production checks)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_org_session
from friday_common.auth import require_role
from friday_common.etims import EtimsConfig, EtimsError, OscuClient, item_body, item_code
from friday_common.etims.codes import PRODUCT_FINISHED, PRODUCT_SERVICE
from friday_common.etims.kernel import automation_on, get_etims_config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product

router = APIRouter(prefix="/products", tags=["etims"])


def quantity_unit(product: Product) -> str:
    """The eTIMS unit of quantity the product is sold in."""
    return getattr(product, "etims_quantity_unit", "") or "U"


async def _next_item_no(session: AsyncSession, org: uuid.UUID) -> int:
    row = await session.execute(
        text(
            """
            INSERT INTO etims_item_sequences (org_id, last_no) VALUES (:org, 1)
            ON CONFLICT (org_id) DO UPDATE SET last_no = etims_item_sequences.last_no + 1
            RETURNING last_no
            """
        ),
        {"org": org},
    )
    return int(row.scalar_one())


async def register_product(session: AsyncSession, product: Product, cfg: dict, client: OscuClient, user: str) -> Product:
    if not product.etims_item_class:
        raise HTTPException(422, "add KRA's item classification code to the product first")
    service = product.kind == "service"
    if not product.etims_item_code:
        seq = await _next_item_no(session, product.org_id)
        product.etims_item_code = item_code(
            PRODUCT_SERVICE if service else PRODUCT_FINISHED, product.etims_packaging_unit or "NT", quantity_unit(product), seq
        )
    body = item_body(
        code=product.etims_item_code,
        name=product.name,
        item_class=product.etims_item_class,
        tax_code=product.tax_code or cfg.get("default_code") or "B",
        price_cents=product.price_cents,
        is_service=service,
        packaging_unit=product.etims_packaging_unit or "NT",
        quantity_unit=quantity_unit(product),
        barcode=product.barcode,
        user=user,
    )
    try:
        await client.save_item(body)
    except EtimsError as exc:
        await session.commit()  # keep the item code; registering again reuses it
        raise HTTPException(502, f"KRA refused the item: {exc}") from None
    product.etims_registered_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(product)
    return product


@router.post("/{product_id}/etims/register")
async def register(
    product_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    if not automation_on():
        raise HTTPException(409, "automatic eTIMS is not switched on for this server yet")
    cfg = await get_etims_config(principal.org_id)
    if not cfg.get("enabled") or not cfg.get("cmc_key"):
        raise HTTPException(409, "turn eTIMS on and add the CMC key in Business settings first")
    product = await session.get(Product, product_id)
    if product is None or str(product.org_id) != principal.org_id:
        raise HTTPException(404, "product not found")
    product = await register_product(session, product, cfg, OscuClient(EtimsConfig.from_kernel(cfg)), principal.email)
    return {"etims_item_code": product.etims_item_code, "etims_registered_at": product.etims_registered_at}
