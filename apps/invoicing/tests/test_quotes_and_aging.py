"""P1 quote-to-cash: quotes, quote -> invoice conversion, tax-inclusive
payment settlement, overdue flag, and AR aging."""

TAXED_LINE = {"description": "Consulting", "quantity": 2, "unit_price_cents": 5000, "tax_rate_bp": 1600}
# 2 x 50.00 = 100.00 subtotal + 16% VAT = 116.00


async def _customer(client, **kw):
    return (await client.post("/customers", json={"name": kw.pop("name", "Acme"), **kw})).json()


async def test_payment_must_cover_tax_before_invoice_is_paid(client):
    """Regression: record_payment used the pre-tax subtotal as the total,
    so paying 100.00 of a 116.00 invoice marked it paid."""
    inv = (await client.post("/invoices", json={"lines": [TAXED_LINE]})).json()
    assert inv["total_cents"] == 11600

    after_subtotal = (await client.post(f"/invoices/{inv['id']}/payments", json={"amount_cents": 10000})).json()
    assert after_subtotal["status"] != "paid"
    assert after_subtotal["balance_cents"] == 1600

    after_tax = (await client.post(f"/invoices/{inv['id']}/payments", json={"amount_cents": 1600})).json()
    assert after_tax["status"] == "paid"
    assert after_tax["balance_cents"] == 0


async def test_quote_lifecycle_and_conversion(client):
    cust = await _customer(client, payment_terms_days=14)
    quote = (
        await client.post("/quotes", json={"customer_id": cust["id"], "lines": [TAXED_LINE], "valid_days": 10})
    ).json()
    assert quote["kind"] == "quote"
    assert quote["number"].startswith("QUO-")
    assert quote["total_cents"] == 11600
    assert quote["valid_until"] is not None

    # Quotes are not invoices: not listed, not payable, not reachable as one.
    assert all(i["id"] != quote["id"] for i in (await client.get("/invoices")).json())
    assert (await client.post(f"/invoices/{quote['id']}/payments", json={"amount_cents": 1})).status_code == 404
    assert (await client.get(f"/invoices/{quote['id']}")).status_code == 404
    assert [q["id"] for q in (await client.get("/quotes")).json()] == [quote["id"]]

    sent = (await client.patch(f"/quotes/{quote['id']}/status", json={"status": "sent"})).json()
    assert sent["status"] == "sent"
    # "accepted" can only come from converting.
    assert (await client.patch(f"/quotes/{quote['id']}/status", json={"status": "accepted"})).status_code == 422

    resp = await client.post(f"/quotes/{quote['id']}/convert")
    assert resp.status_code == 201
    invoice = resp.json()
    assert invoice["kind"] == "invoice"
    assert invoice["status"] == "draft"
    assert invoice["source"] == "quote"
    assert invoice["source_ref"] == quote["id"]
    assert invoice["total_cents"] == 11600
    assert invoice["lines"][0]["tax_rate_bp"] == 1600
    assert invoice["due_at"] is not None

    assert (await client.get(f"/quotes/{quote['id']}")).json()["status"] == "accepted"
    assert (await client.post(f"/quotes/{quote['id']}/convert")).status_code == 409


async def test_declined_quote_cannot_be_converted(client):
    quote = (await client.post("/quotes", json={"lines": [TAXED_LINE]})).json()
    await client.patch(f"/quotes/{quote['id']}/status", json={"status": "declined"})
    assert (await client.post(f"/quotes/{quote['id']}/convert")).status_code == 409


async def test_quote_requires_lines(client):
    assert (await client.post("/quotes", json={"lines": []})).status_code == 422


async def _sent_invoice(client, customer_id, unit_price_cents):
    inv = (
        await client.post(
            "/invoices",
            json={"customer_id": customer_id, "lines": [{"description": "x", "unit_price_cents": unit_price_cents}]},
        )
    ).json()
    return (await client.patch(f"/invoices/{inv['id']}/status", json={"status": "sent"})).json()


async def test_overdue_flag_and_ar_aging_buckets(client):
    # Negative terms put due_at in the past -- the simplest way to age an
    # invoice without reaching into the DB.
    late = await _customer(client, name="Late Ltd", payment_terms_days=-45)
    fresh = await _customer(client, name="Fresh Co", payment_terms_days=30)

    overdue = await _sent_invoice(client, late["id"], 30000)
    current = await _sent_invoice(client, fresh["id"], 20000)
    partly = await _sent_invoice(client, late["id"], 10000)
    await client.post(f"/invoices/{partly['id']}/payments", json={"amount_cents": 4000})
    # Drafts and paid invoices are not receivables.
    await client.post("/invoices", json={"customer_id": late["id"], "lines": [{"description": "d", "unit_price_cents": 999}]})
    paid = await _sent_invoice(client, late["id"], 5000)
    await client.post(f"/invoices/{paid['id']}/payments", json={"amount_cents": 5000})

    assert overdue["is_overdue"] is True and overdue["days_overdue"] >= 44
    assert current["is_overdue"] is False

    report = (await client.get("/reports/ar-aging")).json()
    rows = {r["customer_name"]: r for r in report["rows"]}
    assert rows["Late Ltd"]["days_31_60_cents"] == 30000 + 6000
    assert rows["Late Ltd"]["invoice_count"] == 2
    assert rows["Fresh Co"]["current_cents"] == 20000
    (usd,) = report["totals"]
    assert usd["currency"] == "USD"
    assert usd["total_cents"] == 30000 + 6000 + 20000
