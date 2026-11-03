from friday_common.testing import make_principal


async def test_create_customer(client):
    resp = await client.post("/customers", json={"name": "Jane Doe", "email": "jane@example.com"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Jane Doe"


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


async def test_manual_invoice_line_discount_reduces_total(client):
    resp = await client.post(
        "/invoices",
        json={"lines": [{"description": "Consulting", "quantity": 2, "unit_price_cents": 1000, "discount_bp": 2500}]},
    )
    assert resp.status_code == 201
    body = resp.json()
    # 2 * 1000 * (1 - 0.25) = 1500
    assert body["total_cents"] == 1500
    assert body["lines"][0]["discount_bp"] == 2500


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
