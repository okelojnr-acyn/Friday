import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import FieldSpec, Principal, ResourceSpec, create_app, get_current_principal, get_org_session, resource
from friday_common.access import Scope, require
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    DRIVER_STATUSES,
    FUEL_TYPES,
    PARCEL_STATUSES,
    VEHICLE_STATUSES,
    Driver,
    FuelLog,
    MaintenanceLog,
    Parcel,
    ParcelEvent,
    Vehicle,
)
from .schemas import (
    DriverCreate,
    DriverOut,
    FuelLogCreate,
    FuelLogOut,
    MaintenanceLogCreate,
    MaintenanceLogOut,
    ParcelCreate,
    ParcelEventOut,
    ParcelOut,
    ParcelScan,
    ParcelUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)

resource(
    ResourceSpec(
        name="vehicle",
        app="fleets",
        label="Vehicle",
        label_plural="Vehicles",
        views=("list", "form"),
        search_fields=("name", "plate_number", "vin"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("plate_number", "Plate", "text"),
            FieldSpec("make", "Make", "text"),
            FieldSpec("model", "Model", "text"),
            FieldSpec("year", "Year", "number"),
            FieldSpec("vin", "VIN", "text", list_visible=False),
            FieldSpec("fuel_type", "Fuel type", "select", options=FUEL_TYPES),
            FieldSpec("status", "Status", "select", options=VEHICLE_STATUSES, required=True),
            FieldSpec("odometer", "Odometer", "number"),
            FieldSpec("assigned_driver_name", "Assigned driver", "pick", reference="fleets.driver"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="driver",
        app="fleets",
        label="Driver",
        label_plural="Drivers",
        views=("list", "form"),
        search_fields=("name", "email", "license_number"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("email", "Email", "email"),
            FieldSpec("phone", "Phone", "phone"),
            FieldSpec("license_number", "License #", "text"),
            FieldSpec("license_expires_on", "License expires", "date"),
            FieldSpec("status", "Status", "select", options=DRIVER_STATUSES, required=True),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="maintenance_log",
        app="fleets",
        label="Maintenance Log",
        label_plural="Maintenance Logs",
        views=("list", "form"),
        search_fields=("description", "vendor"),
        fields=(
            FieldSpec("vehicle_id", "Vehicle", "reference", reference="fleets.vehicle", required=True),
            FieldSpec("service_date", "Date", "date", required=True),
            FieldSpec("odometer", "Odometer", "number"),
            FieldSpec("description", "Description", "text", required=True),
            FieldSpec("cost_cents", "Cost", "currency"),
            FieldSpec("vendor", "Vendor", "text"),
        ),
    )
)

resource(
    ResourceSpec(
        name="fuel_log",
        app="fleets",
        label="Fuel Log",
        label_plural="Fuel Logs",
        views=("list", "form"),
        search_fields=(),
        fields=(
            FieldSpec("vehicle_id", "Vehicle", "reference", reference="fleets.vehicle", required=True),
            FieldSpec("fill_date", "Date", "date", required=True),
            FieldSpec("odometer", "Odometer", "number"),
            FieldSpec("quantity", "Quantity", "number", required=True),
            FieldSpec("cost_cents", "Cost", "currency"),
        ),
    )
)

resource(
    ResourceSpec(
        name="parcel",
        app="fleets",
        label="Parcel",
        label_plural="Parcels",
        views=("list", "form"),
        search_fields=("tracking_code", "recipient_name", "recipient_phone", "destination"),
        fields=(
            FieldSpec("tracking_code", "Tracking code", "text", required=True),
            FieldSpec("description", "What it is", "text"),
            FieldSpec("recipient_name", "Recipient", "text"),
            FieldSpec("recipient_phone", "Recipient's phone", "phone"),
            FieldSpec("destination", "Deliver to", "text"),
            FieldSpec("status", "Status", "select", options=PARCEL_STATUSES, form_visible=False),
            FieldSpec("holder_email", "With", "text", form_visible=False),
            FieldSpec("updated_at", "Last scan", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-fleets")


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


vehicles_router = APIRouter(prefix="/vehicles", tags=["vehicles"])
drivers_router = APIRouter(prefix="/drivers", tags=["drivers"])
maintenance_router = APIRouter(prefix="/maintenance_logs", tags=["maintenance-logs"])
fuel_router = APIRouter(prefix="/fuel_logs", tags=["fuel-logs"])


@vehicles_router.get("", response_model=list[VehicleOut])
async def list_vehicles(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Vehicle).where(Vehicle.org_id == _org(principal)).order_by(Vehicle.name))
    return rows.scalars().all()


@vehicles_router.post("", response_model=VehicleOut, status_code=201)
async def create_vehicle(
    body: VehicleCreate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    # The fleet itself (vehicles, drivers) is a manager's to change.
    if scope.kind not in ("all", "loc"):
        raise HTTPException(403, "only a branch manager, admin or owner changes vehicles and drivers")
    if body.fuel_type not in FUEL_TYPES:
        raise HTTPException(422, f"fuel_type must be one of {FUEL_TYPES}")
    if body.status not in VEHICLE_STATUSES:
        raise HTTPException(422, f"status must be one of {VEHICLE_STATUSES}")
    now = datetime.now(UTC)
    vehicle = Vehicle(org_id=_org(principal), created_at=now, updated_at=now, **body.model_dump())
    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)
    return vehicle


async def _get_owned_vehicle(session: AsyncSession, principal: Principal, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None or str(vehicle.org_id) != principal.org_id:
        raise HTTPException(404, "vehicle not found")
    return vehicle


@vehicles_router.get("/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_owned_vehicle(session, principal, vehicle_id)


@vehicles_router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    # The fleet itself (vehicles, drivers) is a manager's to change.
    if scope.kind not in ("all", "loc"):
        raise HTTPException(403, "only a branch manager, admin or owner changes vehicles and drivers")
    vehicle = await _get_owned_vehicle(session, principal, vehicle_id)
    changes = body.model_dump(exclude_unset=True)
    if "fuel_type" in changes and changes["fuel_type"] not in FUEL_TYPES:
        raise HTTPException(422, f"fuel_type must be one of {FUEL_TYPES}")
    if "status" in changes and changes["status"] not in VEHICLE_STATUSES:
        raise HTTPException(422, f"status must be one of {VEHICLE_STATUSES}")
    for field_name, value in changes.items():
        setattr(vehicle, field_name, value)
    vehicle.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(vehicle)
    return vehicle


@drivers_router.get("", response_model=list[DriverOut])
async def list_drivers(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Driver).where(Driver.org_id == _org(principal)).order_by(Driver.name))
    return rows.scalars().all()


@drivers_router.post("", response_model=DriverOut, status_code=201)
async def create_driver(
    body: DriverCreate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    # The fleet itself (vehicles, drivers) is a manager's to change.
    if scope.kind not in ("all", "loc"):
        raise HTTPException(403, "only a branch manager, admin or owner changes vehicles and drivers")
    if body.status not in DRIVER_STATUSES:
        raise HTTPException(422, f"status must be one of {DRIVER_STATUSES}")
    driver = Driver(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(driver)
    await session.commit()
    await session.refresh(driver)
    return driver


@maintenance_router.get("", response_model=list[MaintenanceLogOut])
async def list_maintenance_logs(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(MaintenanceLog)
        .where(MaintenanceLog.org_id == _org(principal))
        .order_by(MaintenanceLog.service_date.desc())
    )
    return rows.scalars().all()


@maintenance_router.post("", response_model=MaintenanceLogOut, status_code=201)
async def create_maintenance_log(
    body: MaintenanceLogCreate,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Also bumps the vehicle's cached odometer when this log's reading
    is newer than what's on file -- same fast-path-cache-plus-ledger
    shape as apps/inventory's Product.on_hand_qty/StockMove."""
    vehicle = await _get_owned_vehicle(session, principal, body.vehicle_id)
    log = MaintenanceLog(org_id=_org(principal), **body.model_dump())
    session.add(log)
    if body.odometer > vehicle.odometer:
        vehicle.odometer = body.odometer
        vehicle.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(log)
    return log


@fuel_router.get("", response_model=list[FuelLogOut])
async def list_fuel_logs(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(FuelLog).where(FuelLog.org_id == _org(principal)).order_by(FuelLog.fill_date.desc())
    )
    return rows.scalars().all()


@fuel_router.post("", response_model=FuelLogOut, status_code=201)
async def create_fuel_log(
    body: FuelLogCreate,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    vehicle = await _get_owned_vehicle(session, principal, body.vehicle_id)
    log = FuelLog(org_id=_org(principal), **body.model_dump())
    session.add(log)
    if body.odometer > vehicle.odometer:
        vehicle.odometer = body.odometer
        vehicle.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(log)
    return log


parcels_router = APIRouter(prefix="/parcels", tags=["parcels"])

# What each scan does to a parcel.
SCAN_STATUS = {"in": "received", "out": "out_for_delivery", "delivered": "delivered", "returned": "returned"}


def _sees(scope: Scope, parcel: Parcel) -> bool:
    """Plan 12.2, deliveries: all; a location's; a team's; or your own
    (the parcels you hold)."""
    if scope.everywhere or parcel.holder_user_id == scope.user_id:
        return True
    if scope.kind == "loc":
        return parcel.location_id is not None and str(parcel.location_id) in scope.locs
    if scope.kind == "team":
        return parcel.holder_user_id in scope.team
    return False


def _event(parcel: Parcel, principal: Principal, status: str, note: str = "") -> ParcelEvent:
    return ParcelEvent(
        org_id=parcel.org_id,
        parcel_id=parcel.id,
        status=status,
        by_user_id=principal.user_id,
        by_email=principal.email,
        note=note.strip(),
        at=datetime.now(UTC),
    )


async def _get_parcel(session: AsyncSession, principal: Principal, scope: Scope, parcel_id: uuid.UUID) -> Parcel:
    parcel = await session.get(Parcel, parcel_id)
    if parcel is None or str(parcel.org_id) != principal.org_id or not _sees(scope, parcel):
        raise HTTPException(404, "parcel not found")
    return parcel


@parcels_router.get("", response_model=list[ParcelOut])
async def list_parcels(
    code: str | None = None,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    query = select(Parcel).where(Parcel.org_id == _org(principal))
    if code:
        query = query.where(Parcel.tracking_code == code.strip())
    rows = await session.execute(query.order_by(Parcel.updated_at.desc()).limit(500))
    return [p for p in rows.scalars().all() if _sees(scope, p)]


@parcels_router.post("", response_model=ParcelOut, status_code=201)
async def create_parcel(
    body: ParcelCreate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """A parcel booked in by hand (the scanner books unknown codes in too)."""
    code = body.tracking_code.strip()
    taken = await session.scalar(select(Parcel).where(Parcel.org_id == _org(principal), Parcel.tracking_code == code))
    if taken is not None:
        raise HTTPException(409, f"parcel {code} is already booked in")
    parcel = _new_parcel(principal, code, **body.model_dump(exclude={"tracking_code"}))
    session.add(parcel)
    await session.flush()
    session.add(_event(parcel, principal, "received", "booked in"))
    await session.commit()
    await session.refresh(parcel)
    return parcel


def _new_parcel(principal: Principal, code: str, **details) -> Parcel:
    now = datetime.now(UTC)
    # Where it came in: the scanner's location, when they work at one.
    locs = [loc for loc in principal.locs if loc != "*"]
    return Parcel(
        org_id=_org(principal),
        tracking_code=code,
        status="received",
        holder_user_id=principal.user_id,
        holder_email=principal.email,
        location_id=uuid.UUID(locs[0]) if len(locs) == 1 else None,
        created_at=now,
        updated_at=now,
        **details,
    )


@parcels_router.get("/{parcel_id}", response_model=ParcelOut)
async def get_parcel(
    parcel_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_parcel(session, principal, scope, parcel_id)


@parcels_router.patch("/{parcel_id}", response_model=ParcelOut)
async def update_parcel(
    parcel_id: uuid.UUID,
    body: ParcelUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """The details (recipient, destination); status changes come from scans."""
    parcel = await _get_parcel(session, principal, scope, parcel_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(parcel, field, value.strip())
    parcel.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(parcel)
    return parcel


@parcels_router.get("/{parcel_id}/events", response_model=list[ParcelEventOut])
async def parcel_history(
    parcel_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.read")),
    session: AsyncSession = Depends(get_org_session),
):
    parcel = await _get_parcel(session, principal, scope, parcel_id)
    rows = await session.execute(select(ParcelEvent).where(ParcelEvent.parcel_id == parcel.id).order_by(ParcelEvent.at))
    return rows.scalars().all()


@parcels_router.post("/scan", response_model=ParcelOut)
async def scan_parcel(
    body: ParcelScan,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("deliveries.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """A scanned tracking code (Guss's Parcels button, plan 16.3):
    - in: received here (an unknown code is booked in);
    - out: out for delivery, and now with whoever scanned it;
    - delivered / returned: only by whoever has it, or someone over them.
    Every scan is recorded in the parcel's history."""
    code = body.code.strip()
    parcel = await session.scalar(
        select(Parcel).where(Parcel.org_id == _org(principal), Parcel.tracking_code == code).with_for_update()
    )
    if parcel is None:
        if body.action != "in":
            raise HTTPException(404, f"no parcel {code}; scan it in first")
        parcel = _new_parcel(principal, code)
        session.add(parcel)
        await session.flush()
    else:
        if body.action in ("delivered", "returned") and not _sees(scope, parcel):
            raise HTTPException(403, f"parcel {code} is with {parcel.holder_email or 'someone else'}; they mark it")
        if parcel.status == "delivered" and body.action != "returned":
            raise HTTPException(409, f"parcel {code} was already delivered")
        parcel.status = SCAN_STATUS[body.action]
        if body.action in ("in", "out"):
            # Picking it up makes it yours.
            parcel.holder_user_id, parcel.holder_email = principal.user_id, principal.email
        parcel.updated_at = datetime.now(UTC)
    session.add(_event(parcel, principal, SCAN_STATUS[body.action], body.note))
    await session.commit()
    await session.refresh(parcel)
    return parcel


app.include_router(parcels_router)
app.include_router(vehicles_router)
app.include_router(drivers_router)
app.include_router(maintenance_router)
app.include_router(fuel_router)
