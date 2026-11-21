"""Plan section 12, step 2 in Inventory: who sees and changes stock, at
which locations, and who orders from suppliers."""

import uuid
from dataclasses import replace

WEST = str(uuid.uuid4())
EAST = str(uuid.uuid4())


async def test_stock_by_job_and_location(client, as_principal, principal):
    admin = replace(principal, role="admin")
    as_principal(admin)
    west = (await client.post("/warehouses", json={"name": "West store", "location_id": WEST})).json()
    east = (await client.post("/warehouses", json={"name": "East store", "location_id": EAST})).json()
    p = (await client.post("/products", json={"name": "Rice", "price_cents": 100})).json()

    # No stock job: no stock at all.
    driver = replace(principal, role="member", perms=("logistics",), locs=(WEST,))
    as_principal(driver)
    assert (await client.get("/products")).status_code == 403
    # A cashier reads stock but doesn't change it.
    cashier = replace(principal, role="member", perms=("cashier",), locs=(WEST,))
    as_principal(cashier)
    assert (await client.get("/products")).status_code == 200
    r = await client.post(f"/products/{p['id']}/adjust-stock", json={"delta": 5, "reason": "received", "warehouse_id": west["id"]})
    assert r.status_code == 403
    # Warehouse staff count stock at their location only.
    stocker = replace(principal, role="member", perms=("warehouse",), locs=(WEST,))
    as_principal(stocker)
    r = await client.post(f"/products/{p['id']}/adjust-stock", json={"delta": 5, "reason": "received", "warehouse_id": west["id"]})
    assert r.status_code == 200, r.text
    r = await client.post(f"/products/{p['id']}/adjust-stock", json={"delta": 5, "reason": "received", "warehouse_id": east["id"]})
    assert r.status_code == 403
    # Their stock history shows their warehouses' moves only.
    as_principal(admin)
    await client.post(f"/products/{p['id']}/adjust-stock", json={"delta": 2, "reason": "received", "warehouse_id": east["id"]})
    as_principal(stocker)
    moves = (await client.get("/stock_moves")).json()
    assert [m["warehouse_id"] for m in moves] == [west["id"]]
    # A warehouse of theirs must be at one of their locations.
    assert (await client.post("/warehouses", json={"name": "Nowhere"})).status_code == 422
    assert (await client.post("/warehouses", json={"name": "East 2", "location_id": EAST})).status_code == 403


async def test_purchasing_needs_the_job(client, as_principal, principal):
    cashier = replace(principal, role="member", perms=("cashier",))
    as_principal(cashier)
    assert (await client.get("/purchase_orders")).status_code == 403
    assert (await client.post("/suppliers", json={"name": "Mill"})).status_code == 403
    buyer = replace(principal, role="member", perms=("purchasing",))
    as_principal(buyer)
    assert (await client.post("/suppliers", json={"name": "Mill"})).status_code == 201
    viewer = replace(principal, role="viewer")
    as_principal(viewer)
    assert (await client.get("/purchase_orders")).status_code == 200
