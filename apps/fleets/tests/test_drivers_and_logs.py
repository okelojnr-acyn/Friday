async def test_create_driver(client):
    resp = await client.post("/drivers", json={"name": "Jane Doe", "license_number": "D12345"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "active"


async def test_create_driver_rejects_unknown_status(client):
    resp = await client.post("/drivers", json={"name": "Jane Doe", "status": "bogus"})
    assert resp.status_code == 422


async def test_create_maintenance_log_bumps_vehicle_odometer(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1", "odometer": 1000})).json()

    resp = await client.post(
        "/maintenance_logs",
        json={
            "vehicle_id": vehicle["id"],
            "service_date": "2026-01-15",
            "odometer": 1500,
            "description": "Oil change",
            "cost_cents": 5000,
            "vendor": "Quick Lube",
        },
    )
    assert resp.status_code == 201

    updated = (await client.get(f"/vehicles/{vehicle['id']}")).json()
    assert updated["odometer"] == 1500


async def test_maintenance_log_does_not_rewind_odometer(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1", "odometer": 5000})).json()

    await client.post(
        "/maintenance_logs",
        json={
            "vehicle_id": vehicle["id"],
            "service_date": "2026-01-15",
            "odometer": 3000,  # lower than current -- e.g. a backdated log
            "description": "Backdated entry",
        },
    )

    updated = (await client.get(f"/vehicles/{vehicle['id']}")).json()
    assert updated["odometer"] == 5000


async def test_maintenance_log_for_unknown_vehicle_404s(client):
    import uuid

    resp = await client.post(
        "/maintenance_logs",
        json={"vehicle_id": str(uuid.uuid4()), "service_date": "2026-01-15", "description": "x"},
    )
    assert resp.status_code == 404


async def test_create_fuel_log_bumps_vehicle_odometer(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1", "odometer": 1000})).json()

    resp = await client.post(
        "/fuel_logs",
        json={"vehicle_id": vehicle["id"], "fill_date": "2026-01-15", "odometer": 1200, "quantity": 40, "cost_cents": 6000},
    )
    assert resp.status_code == 201

    updated = (await client.get(f"/vehicles/{vehicle['id']}")).json()
    assert updated["odometer"] == 1200


async def test_fuel_log_requires_positive_quantity(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1"})).json()
    resp = await client.post(
        "/fuel_logs", json={"vehicle_id": vehicle["id"], "fill_date": "2026-01-15", "quantity": 0}
    )
    assert resp.status_code == 422


async def test_list_maintenance_and_fuel_logs(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1"})).json()
    await client.post(
        "/maintenance_logs",
        json={"vehicle_id": vehicle["id"], "service_date": "2026-01-15", "description": "Oil change"},
    )
    await client.post(
        "/fuel_logs", json={"vehicle_id": vehicle["id"], "fill_date": "2026-01-15", "quantity": 40}
    )

    assert len((await client.get("/maintenance_logs")).json()) == 1
    assert len((await client.get("/fuel_logs")).json()) == 1
