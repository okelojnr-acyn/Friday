"""Plan section 12, step 2 in Invoicing: who may sell at which till, whose
sales each role sees, and who handles invoices and customers."""

import uuid
from dataclasses import replace

WEST = str(uuid.uuid4())
EAST = str(uuid.uuid4())


def sale(cents=1000, **kw):
    body = {
        "client_sale_id": str(uuid.uuid4()),
        "currency": "KES",
        "method": "cash",
        "amount_cents": cents,
        "lines": [{"description": "Soda", "quantity": 1, "unit_price_cents": cents}],
    }
    body.update(kw)
    return body


async def _till(client, as_principal, admin, name, location):
    as_principal(admin)
    r = await client.post("/pos/registers", json={"name": name, "location_id": location})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _open(client, as_principal, who, till):
    as_principal(who)
    r = await client.post("/pos/shifts/open", json={"register_id": till, "opening_float_cents": 0})
    return r


async def test_only_cashiers_sell_and_only_at_their_locations(client, as_principal, principal):
    admin = principal
    west = await _till(client, as_principal, admin, "West 1", WEST)
    east = await _till(client, as_principal, admin, "East 1", EAST)

    stocker = replace(principal, user_id="u-stock", role="member", perms=("warehouse",), locs=(WEST,))
    r = await _open(client, as_principal, stocker, west)
    assert r.status_code == 403 and "ask" in r.json()["detail"]

    sam = replace(principal, user_id="u-sam", role="member", perms=("cashier",), locs=(WEST,))
    assert (await _open(client, as_principal, sam, east)).status_code == 403  # not his location
    shift = await _open(client, as_principal, sam, west)
    assert shift.status_code == 201, shift.text
    made = await client.post("/pos/sales", json=sale(shift_id=shift.json()["id"]))
    assert made.status_code == 201, made.text
    # A sale at West is filed at West.
    as_principal(admin)
    inv = (await client.get(f"/invoices/{made.json()['id']}")).json()
    assert inv["id"] == made.json()["id"]


async def test_whose_sales_each_role_sees(client, as_principal, principal):
    admin = principal
    west = await _till(client, as_principal, admin, "West 2", WEST)
    sam = replace(principal, user_id="u-sam2", role="member", perms=("cashier",), locs=(WEST,))
    ann = replace(principal, user_id="u-ann2", role="member", perms=("cashier",), locs=(WEST,))
    shift = (await _open(client, as_principal, sam, west)).json()
    await client.post("/pos/sales", json=sale(100, shift_id=shift["id"]))
    as_principal(ann)
    await client.post("/pos/sales", json=sale(200, shift_id=shift["id"]))

    from datetime import UTC, datetime

    today = datetime.now(UTC).date().isoformat()

    async def seen(who):
        as_principal(who)
        r = await client.get("/pos/sales", params={"day": today})
        assert r.status_code == 200, r.text
        return sorted(s["total_cents"] for s in r.json())

    assert await seen(sam) == [100]  # own
    lead = replace(principal, user_id="u-lead2", role="team_leader", perms=(), locs=(WEST,), team=("u-ann2",))
    assert await seen(lead) == [200]  # their team (and themselves)
    boss = replace(principal, user_id="u-boss2", role="branch_manager", locs=(WEST,))
    assert 100 in await seen(boss) and 200 in await seen(boss)
    elsewhere = replace(principal, user_id="u-boss3", role="branch_manager", locs=(EAST,))
    assert 100 not in await seen(elsewhere)


async def test_invoices_and_customers_by_role(client, as_principal, principal):
    staff = replace(principal, role="member", perms=("cashier",))
    as_principal(staff)
    assert (await client.post("/invoices", json={})).status_code == 403
    assert (await client.get("/invoices")).status_code == 403
    assert (await client.get("/customers")).status_code == 200  # a cashier serves customers
    no_job = replace(principal, role="member", perms=("warehouse",))
    as_principal(no_job)
    assert (await client.get("/customers")).status_code == 403
    viewer = replace(principal, role="viewer")
    as_principal(viewer)
    assert (await client.get("/invoices")).status_code == 200
    boss = replace(principal, role="branch_manager", locs=(WEST,))
    as_principal(boss)
    assert (await client.get("/reports/ar-aging")).status_code == 403  # whole-business report


async def test_a_branch_manager_runs_tills_at_their_locations_only(client, as_principal, principal):
    boss = replace(principal, role="branch_manager", locs=(WEST,))
    as_principal(boss)
    assert (await client.post("/pos/registers", json={"name": "No place"})).status_code == 422
    assert (await client.post("/pos/registers", json={"name": "East 9", "location_id": EAST})).status_code == 403
    r = await client.post("/pos/registers", json={"name": "West 9", "location_id": WEST})
    assert r.status_code == 201, r.text
    moved = await client.patch(f"/pos/registers/{r.json()['id']}", json={"location_id": EAST})
    assert moved.status_code == 403
