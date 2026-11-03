import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import FieldSpec, Principal, ResourceSpec, create_app, get_current_principal, get_org_session, resource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DRIVER_STATUSES, FUEL_TYPES, VEHICLE_STATUSES, Driver, FuelLog, MaintenanceLog, Vehicle
from .schemas import (
    DriverCreate,
    DriverOut,
    FuelLogCreate,
    FuelLogOut,
    MaintenanceLogCreate,
    MaintenanceLogOut,
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
            FieldSpec("assigned_driver_name", "Assigned driver", "text"),
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
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Vehicle).where(Vehicle.org_id == _org(principal)).order_by(Vehicle.name))
    return rows.scalars().all()


@vehicles_router.post("", response_model=VehicleOut, status_code=201)
async def create_vehicle(
    body: VehicleCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
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
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_owned_vehicle(session, principal, vehicle_id)


@vehicles_router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
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
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Driver).where(Driver.org_id == _org(principal)).order_by(Driver.name))
    return rows.scalars().all()


@drivers_router.post("", response_model=DriverOut, status_code=201)
async def create_driver(
    body: DriverCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
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


app.include_router(vehicles_router)
app.include_router(drivers_router)
app.include_router(maintenance_router)
app.include_router(fuel_router)
