"""A busy evening (owner, 2026-11-16): many tills selling the same item at
once, and a sale delivered twice, must leave stock exactly right."""

import asyncio


def sale(principal, number, lines):
    return {"org_id": principal.org_id, "payload": {"invoice_number": number, "lines": lines}}


async def stock(client, pid):
    return (await client.get(f"/products/{pid}")).json()["on_hand_qty"]


async def test_twenty_tills_selling_one_item_at_once_all_count(client, kernel_auth_header, principal):
    p = (await client.post("/products", json={"name": "Sugar 1kg", "price_cents": 16500, "on_hand_qty": 100})).json()
    sends = [
        client.post(
            "/internal/webhooks/pos-sale",
            headers=kernel_auth_header,
            json=sale(principal, f"POS-RUSH-{i}", [{"product_id": p["id"], "quantity": 1}]),
        )
        for i in range(20)
    ]
    results = await asyncio.gather(*sends)
    assert all(r.status_code == 204 for r in results)
    assert await stock(client, p["id"]) == 80


async def test_a_sale_delivered_twice_comes_off_once(client, kernel_auth_header, principal):
    p = (await client.post("/products", json={"name": "Milk", "price_cents": 6500, "on_hand_qty": 10})).json()
    body = sale(principal, "POS-TWICE-1", [{"product_id": p["id"], "quantity": 2}])
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=body)
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=body)
    assert await stock(client, p["id"]) == 8


async def test_one_product_on_two_lines_and_a_half_unit(client, kernel_auth_header, principal):
    p = (await client.post("/products", json={"name": "Rice", "price_cents": 32000, "on_hand_qty": 10})).json()
    body = sale(
        principal,
        "POS-LINES-1",
        [{"product_id": p["id"], "quantity": 2}, {"product_id": p["id"], "quantity": 1}, {"product_id": p["id"], "quantity": 0.5}],
    )
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=body)
    # 2 + 1 + 0.5 = 3.5 exactly (units, 2026-11-16: nothing is rounded).
    assert await stock(client, p["id"]) == 6.5


async def test_a_return_puts_stock_back(client, kernel_auth_header, principal):
    p = (await client.post("/products", json={"name": "Soap", "price_cents": 11000, "on_hand_qty": 5})).json()
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=sale(principal, "POS-R-1", [{"product_id": p["id"], "quantity": 2}]))
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=sale(principal, "RET-R-1", [{"product_id": p["id"], "quantity": -2}]))
    assert await stock(client, p["id"]) == 5
