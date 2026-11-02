from friday_common.testing import make_principal


async def test_create_product_defaults(client):
    resp = await client.post("/products", json={"name": "Widget", "price_cents": 999})
    assert resp.status_code == 201
    body = resp.json()
    assert body["on_hand_qty"] == 0
    assert body["reorder_point"] == 0
    assert body["track_inventory"] is True


async def test_create_product_with_initial_stock_records_a_received_move(client):
    product = (
        await client.post("/products", json={"name": "Widget", "price_cents": 999, "on_hand_qty": 10})
    ).json()

    moves = (await client.get("/stock_moves")).json()
    assert len(moves) == 1
    assert moves[0]["product_id"] == product["id"]
    assert moves[0]["qty_delta"] == 10
    assert moves[0]["reason"] == "received"


async def test_create_product_with_zero_initial_stock_records_no_move(client):
    await client.post("/products", json={"name": "Widget", "price_cents": 999})
    assert (await client.get("/stock_moves")).json() == []


async def test_adjust_stock_updates_on_hand_qty_and_logs_a_move(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()

    resp = await client.post(
        f"/products/{product['id']}/adjust-stock",
        json={"delta": -3, "reason": "manual_adjustment", "reference": "breakage"},
    )
    assert resp.status_code == 200
    assert resp.json()["on_hand_qty"] == -3

    moves = (await client.get("/stock_moves")).json()
    assert moves[0]["qty_delta"] == -3
    assert moves[0]["reference"] == "breakage"


async def test_adjust_stock_rejects_invalid_reason(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()
    resp = await client.post(f"/products/{product['id']}/adjust-stock", json={"delta": 1, "reason": "bogus"})
    assert resp.status_code == 422


async def test_reorder_point_is_editable(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()
    resp = await client.patch(f"/products/{product['id']}", json={"reorder_point": 5})
    assert resp.status_code == 200
    assert resp.json()["reorder_point"] == 5


async def test_org_isolation_on_products(client, as_principal, principal):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()

    as_principal(make_principal())
    assert (await client.get("/products")).json() == []
    assert (await client.get(f"/products/{product['id']}")).status_code == 404

    as_principal(principal)
    assert (await client.get(f"/products/{product['id']}")).status_code == 200
