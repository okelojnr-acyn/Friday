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

    as_principal(make_principal(role="admin"))  # an admin of another business
    assert (await client.get("/products")).json() == []
    assert (await client.get(f"/products/{product['id']}")).status_code == 404

    as_principal(principal)
    assert (await client.get(f"/products/{product['id']}")).status_code == 200


async def test_stock_moves_filter_by_reference_and_accept_guss_reasons(client):
    product = (await client.post("/products", json={"name": "Soda", "price_cents": 80})).json()
    for delta, reason, ref in [(24, "received", "guss:a"), (-5, "sale", "guss:b"), (-1, "write_off", "other")]:
        resp = await client.post(
            f"/products/{product['id']}/adjust-stock",
            json={"delta": delta, "reason": reason, "reference": ref},
        )
        assert resp.status_code == 200, resp.text

    only = (await client.get("/stock_moves", params={"reference": "guss:b"})).json()
    assert [(m["qty_delta"], m["reason"]) for m in only] == [(-5, "sale")]
    assert len((await client.get("/stock_moves")).json()) == 3
    assert (await client.get("/stock_moves", params={"reference": "missing"})).json() == []


async def test_products_carry_a_shelf_category(client):
    made = (await client.post("/products", json={"name": "Milk 500ml", "price_cents": 6500, "category": "Dairy"})).json()
    assert made["category"] == "Dairy"
    moved = (await client.patch(f"/products/{made['id']}", json={"category": "Fresh"})).json()
    assert moved["category"] == "Fresh"


async def test_counted_stock_is_sent_to_the_books_and_untracked_sales_move_nothing(client, monkeypatch):
    """Plan 20.2: stock counted in or out by hand reaches the books at cost
    (Guss's own restocks, "guss:...", it books itself); a sale of a product
    that doesn't track stock leaves its count alone."""
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    tracked = (await client.post("/products", json={"name": "Yoghurt", "cost_cents": 65000, "track_inventory": True})).json()
    await client.post(f"/products/{tracked['id']}/adjust-stock", json={"delta": 50, "reason": "received"})
    await client.post(f"/products/{tracked['id']}/adjust-stock", json={"delta": 2, "reason": "received", "reference": "guss:abc"})
    await client.post(f"/products/{tracked['id']}/adjust-stock", json={"delta": -2, "reason": "write_off"})
    assert [(t, p["value_cents"], p["reason"]) for t, p in sent] == [
        ("inventory.stock.adjusted", 3250000, "received"),
        ("inventory.stock.adjusted", -130000, "write_off"),
    ]

    untracked = (await client.post("/products", json={"name": "Rice", "track_inventory": False})).json()
    resp = await client.post(f"/products/{untracked['id']}/adjust-stock", json={"delta": -8, "reason": "sale"})
    assert resp.status_code == 200 and resp.json()["on_hand_qty"] == 0
