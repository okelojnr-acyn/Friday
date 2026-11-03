from friday_common.testing import make_principal


async def test_create_vehicle_defaults(client):
    resp = await client.post("/vehicles", json={"name": "Truck 1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "active"
    assert body["fuel_type"] == "gasoline"
    assert body["odometer"] == 0


async def test_create_vehicle_rejects_unknown_fuel_type(client):
    resp = await client.post("/vehicles", json={"name": "Truck 1", "fuel_type": "bogus"})
    assert resp.status_code == 422


async def test_create_vehicle_rejects_unknown_status(client):
    resp = await client.post("/vehicles", json={"name": "Truck 1", "status": "bogus"})
    assert resp.status_code == 422


async def test_update_vehicle(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1"})).json()
    resp = await client.patch(f"/vehicles/{vehicle['id']}", json={"assigned_driver_name": "Jane Doe"})
    assert resp.status_code == 200
    assert resp.json()["assigned_driver_name"] == "Jane Doe"


async def test_update_vehicle_rejects_unknown_status(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1"})).json()
    resp = await client.patch(f"/vehicles/{vehicle['id']}", json={"status": "bogus"})
    assert resp.status_code == 422


async def test_get_vehicle_by_id(client):
    vehicle = (await client.post("/vehicles", json={"name": "Truck 1"})).json()
    resp = await client.get(f"/vehicles/{vehicle['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == vehicle["id"]


async def test_get_unknown_vehicle_404s(client):
    import uuid

    resp = await client.get(f"/vehicles/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_org_isolation_on_vehicles(client, as_principal, principal):
    await client.post("/vehicles", json={"name": "Truck 1"})
    as_principal(make_principal())
    assert (await client.get("/vehicles")).json() == []
