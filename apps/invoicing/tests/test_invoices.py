from friday_common.testing import make_principal


async def test_create_customer(client):
    resp = await client.post("/customers", json={"name": "Jane Doe", "email": "jane@example.com"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Jane Doe"
    assert resp.json()["payment_terms_days"] == 30


async def test_bulk_create_customers(client):
    resp = await client.post(
        "/customers/bulk",
        json={"customers": [{"name": "Alice"}, {"name": "Bob", "payment_terms_days": 14}]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 2
    assert {c["name"] for c in body} == {"Alice", "Bob"}


async def test_bulk_create_customers_requires_at_least_one(client):
    resp = await client.post("/customers/bulk", json={"customers": []})
    assert resp.status_code == 422


async def test_invoice_due_at_set_from_customer_payment_terms(client):
    customer = (
        await client.post("/customers", json={"name": "Jane Doe", "payment_terms_days": 15})
    ).json()
    resp = await client.post(
        "/invoices",
        json={"customer_id": customer["id"], "lines": [{"description": "x", "unit_price_cents": 100}]},
    )
    body = resp.json()
    assert body["due_at"] is not None


async def test_invoice_without_customer_has_no_due_at(client):
    resp = await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 100}]})
    assert resp.json()["due_at"] is None


async def test_create_credit_note_negates_original_lines(client):
    invoice = (
        await client.post(
            "/invoices",
            json={"lines": [{"description": "Widget", "quantity": 2, "unit_price_cents": 1000}]},
        )
    ).json()

    resp = await client.post(f"/invoices/{invoice['id']}/credit-note")
    assert resp.status_code == 201
    note = resp.json()
    assert note["source"] == "credit_note"
    assert note["source_ref"] == invoice["number"]
    assert note["status"] == "paid"
    assert note["total_cents"] == -2000
    assert note["paid_cents"] == -2000
    assert note["balance_cents"] == 0

    original = (await client.get(f"/invoices/{invoice['id']}")).json()
    assert original["status"] == "draft"  # credit note never voids the original


async def test_credit_note_publishes_invoice_paid_with_negative_amount(client, monkeypatch):
    captured = {}

    async def fake(org_id, inv, paid_amount_cents, lines_payload):
        captured["paid_amount_cents"] = paid_amount_cents

    monkeypatch.setattr("app.main.publish_invoice_paid", fake)

    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 500}]})
    ).json()
    await client.post(f"/invoices/{invoice['id']}/credit-note")

    assert captured["paid_amount_cents"] == -500


async def test_create_invoice_with_lines_computes_total(client):
    customer = (await client.post("/customers", json={"name": "Jane Doe"})).json()
    resp = await client.post(
        "/invoices",
        json={
            "customer_id": customer["id"],
            "lines": [
                {"description": "Widget", "quantity": 2, "unit_price_cents": 1000},
                {"description": "Gadget", "quantity": 1, "unit_price_cents": 500},
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["customer_id"] == customer["id"]
    assert body["status"] == "draft"
    assert body["total_cents"] == 2500
    assert body["paid_cents"] == 0
    assert body["balance_cents"] == 2500


async def test_invoice_number_is_unique_per_invoice(client):
    a = (await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 100}]})).json()
    b = (await client.post("/invoices", json={"lines": [{"description": "y", "unit_price_cents": 100}]})).json()
    assert a["number"] != b["number"]


async def test_set_invoice_status_rejects_unknown_status(client):
    invoice = (await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 100}]})).json()
    resp = await client.patch(f"/invoices/{invoice['id']}/status", json={"status": "bogus"})
    assert resp.status_code == 422


async def test_partial_payment_keeps_invoice_unpaid_then_full_payment_marks_paid(client):
    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 1000}]})
    ).json()

    partial = await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 400})
    assert partial.json()["status"] == "draft"
    assert partial.json()["balance_cents"] == 600

    full = await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 600})
    assert full.json()["status"] == "paid"
    assert full.json()["balance_cents"] == 0


async def test_payment_amount_must_be_positive(client):
    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 1000}]})
    ).json()
    resp = await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 0})
    assert resp.status_code == 422


async def test_org_isolation_on_invoices(client, as_principal, principal):
    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 100}]})
    ).json()

    as_principal(make_principal())
    assert (await client.get(f"/invoices/{invoice['id']}")).status_code == 404
    assert (await client.get("/invoices")).json() == []

    as_principal(principal)
    assert (await client.get(f"/invoices/{invoice['id']}")).status_code == 200
