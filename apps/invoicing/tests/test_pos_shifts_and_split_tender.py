async def test_open_shift(client):
    resp = await client.post("/pos/shifts/open", json={"opening_float_cents": 10000})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"
    assert body["opening_float_cents"] == 10000
    assert body["closed_at"] is None


async def test_get_current_shift_404s_when_none_open(client):
    resp = await client.get("/pos/shifts/current")
    assert resp.status_code == 404


async def test_cannot_open_a_second_shift_while_one_is_open(client):
    await client.post("/pos/shifts/open", json={"opening_float_cents": 10000})
    resp = await client.post("/pos/shifts/open", json={"opening_float_cents": 5000})
    assert resp.status_code == 400


async def test_get_current_shift_returns_the_open_one(client):
    opened = (await client.post("/pos/shifts/open", json={"opening_float_cents": 10000})).json()
    resp = await client.get("/pos/shifts/current")
    assert resp.status_code == 200
    assert resp.json()["id"] == opened["id"]


async def test_close_shift_computes_expected_from_opening_float_plus_cash_sales(client):
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 10000})).json()

    await client.post(
        "/pos/sales",
        json={"lines": [{"description": "Coffee", "quantity": 1, "unit_price_cents": 500}], "amount_cents": 500, "method": "cash"},
    )
    await client.post(
        "/pos/sales",
        json={"lines": [{"description": "Pastry", "quantity": 1, "unit_price_cents": 300}], "amount_cents": 300, "method": "card"},
    )

    resp = await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 10500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "closed"
    # opening float 10000 + the one cash sale (500) -- the card sale doesn't count
    assert body["expected_cents"] == 10500
    assert body["closing_count_cents"] == 10500


async def test_cannot_close_an_already_closed_shift(client):
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()
    await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 0})

    resp = await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 0})
    assert resp.status_code == 400


async def test_closing_an_unknown_shift_404s(client):
    import uuid

    resp = await client.post(f"/pos/shifts/{uuid.uuid4()}/close", json={"closing_count_cents": 0})
    assert resp.status_code == 404


async def test_list_shifts_returns_newest_first(client):
    first = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()
    await client.post(f"/pos/shifts/{first['id']}/close", json={"closing_count_cents": 0})
    second = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()

    shifts = (await client.get("/pos/shifts")).json()
    assert shifts[0]["id"] == second["id"]
    assert shifts[1]["id"] == first["id"]


async def test_split_tender_sale_creates_two_payment_rows(client):
    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 1000}],
            "amount_cents": 1000,
            "payments": [
                {"method": "cash", "amount_cents": 600},
                {"method": "card", "amount_cents": 400},
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_cents"] == 1000
    assert body["paid_cents"] == 1000
    assert body["balance_cents"] == 0
    assert len(body["payments"]) == 2
    methods = {p["method"]: p["amount_cents"] for p in body["payments"]}
    assert methods == {"cash": 600, "card": 400}


async def test_split_tender_rejects_mismatched_total(client):
    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 1000}],
            "amount_cents": 1000,
            "payments": [
                {"method": "cash", "amount_cents": 600},
                {"method": "card", "amount_cents": 300},
            ],
        },
    )
    assert resp.status_code == 422


async def test_split_tender_cash_portion_counts_toward_shift_reconciliation(client):
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()

    await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 1000}],
            "amount_cents": 1000,
            "payments": [
                {"method": "cash", "amount_cents": 600},
                {"method": "card", "amount_cents": 400},
            ],
        },
    )

    resp = await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 600})
    assert resp.json()["expected_cents"] == 600
