"""Moving stock between stores: two moves written together, never more
than the first store has, only between the caller's places, the total
unchanged."""

import uuid

from friday_common.testing import make_principal


async def _setup(client):
    shop = str(uuid.uuid4())
    back = (await client.post("/warehouses", json={"name": "Back store", "location_id": str(uuid.uuid4())})).json()
    town = (await client.post("/warehouses", json={"name": "Town branch", "location_id": shop})).json()
    product = (
        await client.post(
            "/products",
            json={"name": "Sugar", "price_cents": 150, "on_hand_qty": 20, "track_inventory": True, "default_warehouse_id": back["id"]},
        )
    ).json()
    return shop, back, town, product


async def test_a_transfer_moves_stock_and_keeps_the_total(client):
    _shop, back, town, product = await _setup(client)

    def move(qty, src=back, dst=town):
        return client.post(
            f"/products/{product['id']}/transfer",
            json={"from_warehouse_id": src["id"], "to_warehouse_id": dst["id"], "qty": qty, "note": "Saturday restock"},
        )

    r = await move(8)
    assert r.status_code == 200 and float(r.json()["on_hand_qty"]) == 20
    levels = {x["warehouse"]: float(x["qty"]) for x in (await client.get(f"/products/{product['id']}/stock-by-location")).json()}
    assert levels == {"Back store": 12.0, "Town branch": 8.0}

    r = await move(50)
    assert r.status_code == 409 and "only 12" in r.json()["detail"]
    assert (await move(1, back, back)).status_code == 422
    assert (await move(0)).status_code == 422
    # A transfer can't be faked through the adjust route (it would change the total).
    r = await client.post(f"/products/{product['id']}/adjust-stock", json={"delta": 5, "reason": "transfer"})
    assert r.status_code == 422


async def test_only_between_my_own_places(client, as_principal, principal):
    shop, back, town, product = await _setup(client)
    # A warehouse worker at the town branch can't move stock out of the back store.
    as_principal(make_principal(org_id=principal.org_id, role="member", perms=("warehouse",), locs=(shop,)))
    r = await client.post(
        f"/products/{product['id']}/transfer",
        json={"from_warehouse_id": back["id"], "to_warehouse_id": town["id"], "qty": 1},
    )
    assert r.status_code == 403
