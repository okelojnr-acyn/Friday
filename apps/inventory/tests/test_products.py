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


async def test_create_product_defaults_to_kind_product(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()
    assert product["kind"] == "product"


async def test_creating_a_service_forces_track_inventory_off(client):
    service = (
        await client.post(
            "/products", json={"name": "Consulting hour", "kind": "service", "price_cents": 10000, "track_inventory": True}
        )
    ).json()
    assert service["kind"] == "service"
    assert service["track_inventory"] is False


async def test_create_product_rejects_invalid_kind(client):
    resp = await client.post("/products", json={"name": "Widget", "price_cents": 999, "kind": "bogus"})
    assert resp.status_code == 422


async def test_updating_a_product_to_kind_service_forces_track_inventory_off(client):
    product = (
        await client.post("/products", json={"name": "Widget", "price_cents": 999, "track_inventory": True})
    ).json()
    resp = await client.patch(f"/products/{product['id']}", json={"kind": "service"})
    assert resp.status_code == 200
    assert resp.json()["track_inventory"] is False


async def test_bulk_create_products_creates_each_row_and_records_stock_moves(client):
    resp = await client.post(
        "/products/bulk",
        json={
            "products": [
                {"name": "Widget", "barcode": "111", "price_cents": 500, "on_hand_qty": 5},
                {"name": "Gadget", "barcode": "222", "price_cents": 1200, "on_hand_qty": 0},
                {"name": "Consulting hour", "kind": "service", "price_cents": 10000},
            ]
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 3
    assert body[2]["kind"] == "service"
    assert body[2]["track_inventory"] is False

    listed = (await client.get("/products")).json()
    assert len(listed) == 3

    moves = (await client.get("/stock_moves")).json()
    bulk_moves = [m for m in moves if m["reference"] == "bulk add"]
    assert len(bulk_moves) == 1  # only the Widget row had nonzero initial stock
    assert bulk_moves[0]["qty_delta"] == 5


async def test_bulk_create_products_rejects_empty_list(client):
    resp = await client.post("/products/bulk", json={"products": []})
    assert resp.status_code == 422


async def test_org_isolation_on_products(client, as_principal, principal):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()

    as_principal(make_principal())
    assert (await client.get("/products")).json() == []
    assert (await client.get(f"/products/{product['id']}")).status_code == 404

    as_principal(principal)
    assert (await client.get(f"/products/{product['id']}")).status_code == 200
