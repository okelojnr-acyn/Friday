"""invoicing.invoice.paid -- the event Accounting subscribes to for
cash-basis journal postings. Covers all four places an invoice actually
becomes paid: a manual payment, the Stripe webhook, a POS sale (always
already-paid), and a POS return (negative amount)."""


async def _capture(monkeypatch, target: str) -> dict:
    captured = {}

    async def fake(org_id, inv, paid_amount_cents, lines_payload, **_):
        captured["org_id"] = org_id
        captured["paid_amount_cents"] = paid_amount_cents
        captured["lines_payload"] = lines_payload
        captured["invoice_number"] = inv.number

    monkeypatch.setattr(target, fake)
    return captured


async def test_full_payment_publishes_invoice_paid(client, principal, monkeypatch):
    captured = await _capture(monkeypatch, "app.main.publish_invoice_paid")

    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 1000}]})
    ).json()
    resp = await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 1000})
    assert resp.status_code == 201

    assert captured["org_id"] == principal.org_id
    assert captured["paid_amount_cents"] == 1000
    assert captured["invoice_number"] == invoice["number"]


async def test_partial_payment_does_not_publish_invoice_paid(client, monkeypatch):
    captured = await _capture(monkeypatch, "app.main.publish_invoice_paid")

    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 1000}]})
    ).json()
    await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 400})

    assert captured == {}


async def test_second_payment_on_already_paid_invoice_does_not_republish(client, monkeypatch):
    captured = await _capture(monkeypatch, "app.main.publish_invoice_paid")

    invoice = (
        await client.post("/invoices", json={"lines": [{"description": "x", "unit_price_cents": 1000}]})
    ).json()
    await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 1000})
    assert captured.get("paid_amount_cents") == 1000

    captured.clear()
    await client.post(f"/invoices/{invoice['id']}/payments", json={"amount_cents": 1})
    assert captured == {}


async def test_pos_sale_publishes_invoice_paid(client, principal, monkeypatch):
    captured = await _capture(monkeypatch, "app.main.publish_invoice_paid")

    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Coffee", "quantity": 2, "unit_price_cents": 300}],
            "amount_cents": 600,
            "method": "cash",
        },
    )
    assert resp.status_code == 201

    assert captured["org_id"] == principal.org_id
    assert captured["paid_amount_cents"] == 600


async def test_pos_return_publishes_invoice_paid_with_negative_amount(client, monkeypatch):
    sale = (
        await client.post(
            "/pos/sales",
            json={
                "lines": [{"description": "Coffee", "quantity": 1, "unit_price_cents": 500}],
                "amount_cents": 500,
            },
        )
    ).json()

    captured = await _capture(monkeypatch, "app.main.publish_invoice_paid")
    resp = await client.post(f"/pos/sales/{sale['number']}/return")
    assert resp.status_code == 201

    assert captured["paid_amount_cents"] == -500


async def test_stripe_webhook_publishes_invoice_paid(client, principal, monkeypatch):
    inv = (
        await client.post(
            "/invoices", json={"lines": [{"description": "Consulting", "unit_price_cents": 5000}]}
        )
    ).json()

    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123", "webhook_secret": "whsec_123"}

    class _AlwaysValidSignature:
        def __init__(self, config):
            pass

        def verify_webhook_signature(self, raw_body, sig_header):
            return True

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.StripeProvider", _AlwaysValidSignature)
    captured = await _capture(monkeypatch, "app.webhooks.publish_invoice_paid")

    resp = await client.post(
        "/external/webhooks/stripe",
        json={
            "type": "payment_intent.succeeded",
            "data": {"object": {"metadata": {"org_id": principal.org_id, "invoice_id": inv["id"]}, "amount_received": 5000}},
        },
        headers={"stripe-signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert captured["paid_amount_cents"] == 5000


async def test_a_till_sale_event_carries_its_vat_and_how_it_was_paid(client, monkeypatch):
    # Accounting books from this event: revenue without VAT, VAT to 2200,
    # and each payment to the account it landed in. The payments must add
    # up to the amount, rounding line included, or it all falls back to cash.
    captured = []

    async def fake_publish_event(event_type, org_id, payload, **_):
        captured.append((event_type, payload))

    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    await client.post(
        "/pos/sales",
        json={
            "lines": [
                {"description": "Cooking oil 1L", "quantity": 2, "unit_price_cents": 58000, "tax_code": "B", "vat_cents": 16000},
                {"description": "Maize flour 2kg", "quantity": 1, "unit_price_cents": 5000, "tax_code": "A", "vat_cents": 0},
            ],
            # 1,210.00 of goods charged 1,209.90: a 0.10 rounding line.
            "amount_cents": 120990,
            "payments": [{"method": "cash", "amount_cents": 70990}, {"method": "mpesa", "amount_cents": 50000}],
        },
    )
    paid = [p for t, p in captured if t == "invoicing.invoice.paid"]
    assert len(paid) == 1
    p = paid[0]
    assert p["vat_cents"] == 16000
    assert p["vat_by_code"] == {"B": 16000, "A": 0}
    assert p["subtotal_cents"] + p["tax_cents"] == 120990
    assert sum(x["amount_cents"] for x in p["payments"]) == 120990
    assert {x["method"] for x in p["payments"]} == {"cash", "mpesa"}


async def test_a_till_return_event_reverses_the_vat(client, monkeypatch):
    sale = (
        await client.post(
            "/pos/sales",
            json={
                "lines": [{"description": "Cooking oil 1L", "quantity": 1, "unit_price_cents": 58000, "tax_code": "B", "vat_cents": 8000}],
                "amount_cents": 58000,
            },
        )
    ).json()
    captured = []

    async def fake_publish_event(event_type, org_id, payload, **_):
        captured.append((event_type, payload))

    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    await client.post(f"/pos/sales/{sale['number']}/return")
    paid = [p for t, p in captured if t == "invoicing.invoice.paid"]
    assert len(paid) == 1
    assert paid[0]["vat_cents"] == -8000
    assert paid[0]["subtotal_cents"] + paid[0]["tax_cents"] == -58000
