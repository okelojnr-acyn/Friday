import uuid


async def test_create_supplier(client):
    resp = await client.post("/suppliers", json={"name": "Acme Supply Co", "email": "orders@acme.test"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Acme Supply Co"


async def test_create_purchase_order_with_lines(client):
    supplier = (await client.post("/suppliers", json={"name": "Acme Supply Co"})).json()
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999, "cost_cents": 400})).json()

    resp = await client.post(
        "/purchase_orders",
        json={
            "supplier_id": supplier["id"],
            "lines": [{"product_id": product["id"], "description": "Widget", "quantity": 10, "unit_cost_cents": 400}],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["total_cost_cents"] == 4000
    assert len(body["lines"]) == 1


async def test_purchase_order_status_rejects_invalid_value(client):
    po = (await client.post("/purchase_orders", json={})).json()
    resp = await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "bogus"})
    assert resp.status_code == 422


async def test_receiving_a_purchase_order_restocks_tracked_products(client):
    product = (
        await client.post(
            "/products", json={"name": "Widget", "price_cents": 999, "cost_cents": 400, "on_hand_qty": 5}
        )
    ).json()
    po = (
        await client.post(
            "/purchase_orders",
            json={"lines": [{"product_id": product["id"], "quantity": 20, "unit_cost_cents": 400}]},
        )
    ).json()

    resp = await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})
    assert resp.status_code == 200

    updated_product = (await client.get(f"/products/{product['id']}")).json()
    assert updated_product["on_hand_qty"] == 25

    moves = (await client.get("/stock_moves")).json()
    received = [m for m in moves if m["reason"] == "received" and m["reference"] == po["number"]]
    assert len(received) == 1
    assert received[0]["qty_delta"] == 20


async def test_receiving_a_purchase_order_twice_does_not_double_restock(client):
    product = (
        await client.post("/products", json={"name": "Widget", "price_cents": 999, "on_hand_qty": 0})
    ).json()
    po = (
        await client.post(
            "/purchase_orders", json={"lines": [{"product_id": product["id"], "quantity": 10}]}
        )
    ).json()

    await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})
    await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})

    updated_product = (await client.get(f"/products/{product['id']}")).json()
    assert updated_product["on_hand_qty"] == 10


async def test_create_purchase_order_from_low_stock_product(client):
    product = (
        await client.post(
            "/products",
            json={"name": "Widget", "price_cents": 999, "cost_cents": 400, "on_hand_qty": 2, "reorder_point": 10},
        )
    ).json()

    resp = await client.post(f"/purchase_orders/from-product/{product['id']}")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["product_id"] == product["id"]
    assert body["lines"][0]["quantity"] == 18  # reorder_point * 2 - on_hand_qty


async def test_create_purchase_order_from_product_requires_existing_product(client):
    resp = await client.post(f"/purchase_orders/from-product/{uuid.uuid4()}")
    assert resp.status_code == 404
