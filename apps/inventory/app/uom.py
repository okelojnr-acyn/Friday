"""Units of measure: the preloaded set, benching, and the conversions a
product's base, purchase and sales units rely on.

Stock is kept in each product's base unit. A purchase unit holds
`purchase_factor` base units and a sales unit `sales_factor`:
- two units of the same category with ratios convert by those ratios
  (base kg, sold per 500 g: 0.5), and the factor is not typed by hand;
- a pack (carton, crate, ...) or a unit from another category (base kg,
  sold per piece of about 0.4 kg) needs the factor given per product.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from friday_common import Principal, get_current_principal, get_org_session
from friday_common.auth import require_role
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, UnitOfMeasure
from .schemas import UnitOfMeasureCreate, UnitOfMeasureOut, UnitOfMeasurePatch

CATEGORIES = ("unit", "weight", "volume", "length", "area", "time")

# code, name, symbol, category, ratio (None = pack), eTIMS unit of quantity.
# eTIMS codes from KRA's OSCU specification v2.0, section 4.7; "" where
# KRA has none (the sale is then reported in the base unit).
STANDARD: tuple[tuple[str, str, str, str, str | None, str], ...] = (
    ("pc", "Piece", "pc", "unit", "1", "U"),
    ("pair", "Pair", "pr", "unit", "2", "PR"),
    ("dozen", "Dozen", "dz", "unit", "12", "DZ"),
    ("gross", "Gross (144)", "gro", "unit", "144", "GRO"),
    ("sheet", "Sheet", "sht", "unit", "1", "ST"),
    ("pack", "Pack", "pk", "unit", None, "PA"),
    ("packet", "Packet", "pkt", "unit", None, "PA"),
    ("box", "Box", "box", "unit", None, "BX"),
    ("carton", "Carton", "ctn", "unit", None, ""),
    ("crate", "Crate", "crt", "unit", None, ""),
    ("tray", "Tray", "tray", "unit", None, ""),
    ("bag", "Bag", "bag", "unit", None, "BG"),
    ("sack", "Sack", "sack", "unit", None, "BG"),
    ("bale", "Bale", "bale", "unit", None, ""),
    ("bundle", "Bundle", "bdl", "unit", None, "BE"),
    ("roll", "Roll", "roll", "unit", None, "RO"),
    ("can", "Can", "can", "unit", None, "CA"),
    ("bottle", "Bottle", "btl", "unit", None, ""),
    ("jerrycan", "Jerrycan", "jcn", "unit", None, ""),
    ("set", "Set", "set", "unit", None, "SET"),
    ("kg", "Kilogram", "kg", "weight", "1", "KG"),
    ("g", "Gram", "g", "weight", "0.001", "GRM"),
    ("mg", "Milligram", "mg", "weight", "0.000001", "MGM"),
    ("t", "Tonne", "t", "weight", "1000", "TNE"),
    ("lb", "Pound", "lb", "weight", "0.45359237", "LBR"),
    ("l", "Litre", "L", "volume", "1", "LTR"),
    ("ml", "Millilitre", "ml", "volume", "0.001", ""),
    ("m3", "Cubic metre", "m³", "volume", "1000", "M3"),
    ("gal", "Gallon", "gal", "volume", "3.785411784", "GLL"),
    ("m", "Metre", "m", "length", "1", "MTR"),
    ("cm", "Centimetre", "cm", "length", "0.01", "CMT"),
    ("km", "Kilometre", "km", "length", "1000", "KTM"),
    ("ft", "Foot", "ft", "length", "0.3048", ""),
    ("yd", "Yard", "yd", "length", "0.9144", "YRD"),
    ("m2", "Square metre", "m²", "area", "1", "M2"),
    ("hr", "Hour", "hr", "time", "1", ""),
    ("day", "Day", "day", "time", "24", ""),
)

router = APIRouter(prefix="/units_of_measure", tags=["units-of-measure"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def ensure_standard_units(session: AsyncSession, org: uuid.UUID) -> None:
    """Adds any preloaded unit this org doesn't have yet. Cheap to repeat."""
    have = (
        await session.execute(select(func.count()).select_from(UnitOfMeasure).where(UnitOfMeasure.org_id == org, UnitOfMeasure.code != ""))
    ).scalar_one()
    if have >= len(STANDARD):
        return
    for i, (code, name, symbol, category, ratio, etims) in enumerate(STANDARD):
        await session.execute(
            text(
                """
                INSERT INTO units_of_measure (id, org_id, name, abbreviation, code, category, ratio, etims_code, sort, created_at)
                VALUES (gen_random_uuid(), :org, :name, :symbol, :code, :category, :ratio, :etims, :sort, now())
                ON CONFLICT (org_id, code) WHERE code <> '' DO NOTHING
                """
            ),
            {"org": org, "name": name, "symbol": symbol, "code": code, "category": category, "ratio": Decimal(ratio) if ratio else None, "etims": etims, "sort": i},
        )
    await session.flush()


async def unit_by_code(session: AsyncSession, org: uuid.UUID, code: str) -> UnitOfMeasure:
    await ensure_standard_units(session, org)
    u = (await session.execute(select(UnitOfMeasure).where(UnitOfMeasure.org_id == org, UnitOfMeasure.code == code))).scalar_one()
    return u


def fixed_factor(base: UnitOfMeasure, unit: UnitOfMeasure) -> Decimal | None:
    """Base units in one `unit`, when the two convert by themselves."""
    if base.id == unit.id:
        return Decimal(1)
    if base.ratio is not None and unit.ratio is not None and base.category == unit.category:
        return (Decimal(unit.ratio) / Decimal(base.ratio)).quantize(Decimal("0.000001"))
    return None


async def _unit(session: AsyncSession, org: uuid.UUID, uom_id: uuid.UUID | None, what: str) -> UnitOfMeasure | None:
    if uom_id is None:
        return None
    u = await session.get(UnitOfMeasure, uom_id)
    if u is None or u.org_id != org:
        raise HTTPException(422, f"{what}: that unit isn't in this organisation")
    return u


async def settle_units(session: AsyncSession, org: uuid.UUID, product: Product, given: dict) -> None:
    """Sets a product's base, purchase and sales units and their factors
    from what the request gave (and the product had). A product always
    ends with a base unit (a piece by default); a purchase or sales unit
    left out is the base unit."""
    base = await _unit(session, org, product.base_uom_id, "base_uom_id")
    if base is None:
        base = await unit_by_code(session, org, "pc")
        product.base_uom_id = base.id
    for kind in ("purchase", "sales"):
        uid = getattr(product, f"{kind}_uom_id") or base.id
        setattr(product, f"{kind}_uom_id", uid)
        unit = await _unit(session, org, uid, f"{kind}_uom_id")
        assert unit is not None
        fixed = fixed_factor(base, unit)
        if fixed is not None:
            setattr(product, f"{kind}_factor", fixed)
            continue
        # A pack, or another category: the size comes from the request,
        # or stays as it was when neither unit changed.
        if given.get(f"{kind}_factor") is not None:
            factor = given[f"{kind}_factor"]
        elif f"{kind}_uom_id" in given or "base_uom_id" in given:
            factor = None
        else:
            factor = getattr(product, f"{kind}_factor")
        if factor is None or Decimal(factor) <= 0:
            raise HTTPException(
                422,
                f"how many {base.abbreviation or base.name} are in one {unit.name.lower()}? Give {kind}_factor",
            )
        setattr(product, f"{kind}_factor", Decimal(factor))


@router.get("", response_model=list[UnitOfMeasureOut])
async def list_units(
    include_benched: bool = True,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    org = _org(principal)
    await ensure_standard_units(session, org)
    await session.commit()
    q = select(UnitOfMeasure).where(UnitOfMeasure.org_id == org)
    if not include_benched:
        q = q.where(UnitOfMeasure.active)
    units = (await session.execute(q.order_by(UnitOfMeasure.sort, UnitOfMeasure.name))).scalars().all()
    used = await _use_counts(session, org)
    return [UnitOfMeasureOut.model_validate(u).model_copy(update={"products_using": used.get(u.id, 0)}) for u in units]


async def _use_counts(session: AsyncSession, org: uuid.UUID) -> dict[uuid.UUID, int]:
    out: dict[uuid.UUID, int] = {}
    for col in (Product.base_uom_id, Product.purchase_uom_id, Product.sales_uom_id):
        rows = await session.execute(
            select(col, func.count(func.distinct(Product.id))).where(Product.org_id == org, col.is_not(None)).group_by(col)
        )
        for uid, n in rows:
            out[uid] = out.get(uid, 0) + n
    return out


@router.post("", response_model=UnitOfMeasureOut, status_code=201)
async def create_unit(
    body: UnitOfMeasureCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """A unit of the business's own: a pack (no ratio; each product sets its
    size) or a measured unit with its ratio to the category's reference."""
    if body.category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    if body.ratio is not None and body.ratio <= 0:
        raise HTTPException(422, "ratio must be more than 0")
    unit = UnitOfMeasure(
        org_id=_org(principal),
        name=body.name.strip(),
        abbreviation=body.abbreviation.strip(),
        category=body.category,
        ratio=body.ratio,
        etims_code=body.etims_code.strip().upper(),
        created_at=datetime.now(UTC),
        sort=500,
    )
    session.add(unit)
    await session.commit()
    await session.refresh(unit)
    return unit


@router.patch("/{unit_id}", response_model=UnitOfMeasureOut)
async def update_unit(
    unit_id: uuid.UUID,
    body: UnitOfMeasurePatch,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Bench or bring back a unit, or rename one. A unit a product uses
    can't be benched, and a preloaded unit's size never changes."""
    org = _org(principal)
    unit = await session.get(UnitOfMeasure, unit_id)
    if unit is None or unit.org_id != org:
        raise HTTPException(404, "unit not found")
    if body.active is False and unit.active:
        used = (
            await session.execute(
                select(func.count()).select_from(Product).where(
                    Product.org_id == org,
                    or_(Product.base_uom_id == unit.id, Product.purchase_uom_id == unit.id, Product.sales_uom_id == unit.id),
                )
            )
        ).scalar_one()
        if used:
            raise HTTPException(409, f"{used} product(s) use {unit.name}; change them before benching it")
    if body.active is not None:
        unit.active = body.active
    if body.name is not None:
        unit.name = body.name.strip()
    if body.abbreviation is not None:
        unit.abbreviation = body.abbreviation.strip()
    if body.etims_code is not None:
        unit.etims_code = body.etims_code.strip().upper()
    if body.ratio is not None:
        if unit.code:
            raise HTTPException(422, "a preloaded unit's size is fixed")
        if body.ratio <= 0:
            raise HTTPException(422, "ratio must be more than 0")
        unit.ratio = body.ratio
    await session.commit()
    await session.refresh(unit)
    used = await _use_counts(session, org)
    return UnitOfMeasureOut.model_validate(unit).model_copy(update={"products_using": used.get(unit.id, 0)})
