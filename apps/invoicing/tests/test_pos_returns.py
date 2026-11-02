import uuid


async def test_get_pos_sale_by_number(client):
    sale = (
        await client.post(
            "/pos/sales",
            json={"lines": [{"description": "Coffee", "quantity": 2, "unit_price_cents": 300}], "amount_cents": 600},
        )
    ).json()

    resp = await client.get(f"/pos/sales/{sale['number']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sale["id"]


async def test_get_pos_sale_404s_for_unknown_number(client):
    resp = await client.get("/pos/sales/POS-NOPE")
    assert resp.status_code == 404


async def test_return_pos_sale_creates_mirrored_negative_invoice_and_voids_original(client):
    product_id = str(uuid.uuid4())
    sale = (
        await client.post(
            "/pos/sales",
            json={
                "lines": [
                    {"description": "Widget", "quantity": 2, "unit_price_cents": 500, "product_id": product_id}
                ],
                "amount_cents": 1000,
                "method": "cash",
            },
        )
    ).json()

    resp = await client.post(f"/pos/sales/{sale['number']}/return")
    assert resp.status_code == 201
    refund = resp.json()
    assert refund["source_ref"] == sale["number"]
    assert refund["total_cents"] == -1000
    assert refund["paid_cents"] == -1000
    assert refund["lines"][0]["quantity"] == "-2.00" or float(refund["lines"][0]["quantity"]) == -2
    assert refund["lines"][0]["product_id"] == product_id

    original = (await client.get(f"/invoices/{sale['id']}")).json()
    assert original["status"] == "void"


async def test_return_pos_sale_restocks_via_existing_inventory_webhook(client, monkeypatch):
    product_id = str(uuid.uuid4())
    captured = []

    async def fake_publish_event(event_type, org_id, payload):
        captured.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish_event)

    sale = (
        await client.post(
            "/pos/sales",
            json={
                "lines": [
                    {"description": "Widget", "quantity": 3, "unit_price_cents": 400, "product_id": product_id}
                ],
                "amount_cents": 1200,
            },
        )
    ).json()
    captured.clear()  # drop the sale's own publish, only the return's matters here

    await client.post(f"/pos/sales/{sale['number']}/return")

    assert len(captured) == 1
    event_type, payload = captured[0]
    assert event_type == "invoicing.pos_sale.recorded"
    assert payload["lines"] == [{"product_id": product_id, "quantity": -3.0}]


async def test_cannot_return_an_already_voided_sale(client):
    sale = (
        await client.post(
            "/pos/sales",
            json={"lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 500}], "amount_cents": 500},
        )
    ).json()

    first = await client.post(f"/pos/sales/{sale['number']}/return")
    assert first.status_code == 201

    second = await client.post(f"/pos/sales/{sale['number']}/return")
    assert second.status_code == 400
