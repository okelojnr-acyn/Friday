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
