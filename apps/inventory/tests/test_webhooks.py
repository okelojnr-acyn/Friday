async def test_pos_sale_recorded_decrements_tracked_product_stock(client, kernel_auth_header, principal):
    product = (
        await client.post(
            "/products", json={"name": "Coffee", "price_cents": 300, "on_hand_qty": 20, "track_inventory": True}
        )
    ).json()

    resp = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_number": "POS-20261101-ABC123",
                "lines": [{"product_id": product["id"], "quantity": 3}],
            },
        },
    )
    assert resp.status_code == 204

    updated = (await client.get(f"/products/{product['id']}")).json()
    assert updated["on_hand_qty"] == 17

    moves = (await client.get("/stock_moves")).json()
    pos_moves = [m for m in moves if m["reason"] == "pos_sale"]
    assert len(pos_moves) == 1
    assert pos_moves[0]["qty_delta"] == -3
    assert pos_moves[0]["reference"] == "POS-20261101-ABC123"


async def test_pos_sale_recorded_skips_products_not_tracking_inventory(client, kernel_auth_header, principal):
    product = (
        await client.post(
            "/products", json={"name": "Consulting hour", "price_cents": 10000, "track_inventory": False}
        )
    ).json()

    await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json={"org_id": principal.org_id, "payload": {"lines": [{"product_id": product["id"], "quantity": 1}]}},
    )

    updated = (await client.get(f"/products/{product['id']}")).json()
    assert updated["on_hand_qty"] == 0
    assert (await client.get("/stock_moves")).json() == []


async def test_pos_sale_recorded_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/pos-sale",
        json={"org_id": principal.org_id, "payload": {"lines": []}},
    )
    assert resp.status_code == 401


async def test_a_sale_at_a_till_takes_stock_from_its_locations_warehouse(client, kernel_auth_header, principal, as_principal):
    import uuid

    from friday_common.testing import make_principal

    shop = str(uuid.uuid4())
    store = (await client.post("/warehouses", json={"name": "Back store"})).json()
    branch = (await client.post("/warehouses", json={"name": "Town branch", "location_id": shop})).json()
    product = (
        await client.post(
            "/products",
            json={"name": "Sugar", "price_cents": 150, "on_hand_qty": 20, "track_inventory": True, "default_warehouse_id": store["id"]},
        )
    ).json()

    resp = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {"invoice_number": "POS-LOC-1", "location_id": shop, "lines": [{"product_id": product["id"], "quantity": 3}]},
        },
    )
    assert resp.status_code == 204
    levels = {r["warehouse"]: float(r["qty"]) for r in (await client.get(f"/products/{product['id']}/stock-by-location")).json()}
    assert levels == {"Back store": 20.0, "Town branch": -3.0}
    assert (await client.get(f"/products/{product['id']}")).json()["on_hand_qty"] == 17

    # A branch manager there sees only their location's warehouse.
    as_principal(make_principal(org_id=principal.org_id, role="branch_manager", locs=(shop,)))
    mine = (await client.get(f"/products/{product['id']}/stock-by-location")).json()
    assert [r["warehouse"] for r in mine] == ["Town branch"]
    assert branch["location_id"] == shop
