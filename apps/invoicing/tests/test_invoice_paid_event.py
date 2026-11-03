"""invoicing.invoice.paid -- the event Accounting subscribes to for
cash-basis journal postings. Covers all four places an invoice actually
becomes paid: a manual payment, the Stripe webhook, a POS sale (always
already-paid), and a POS return (negative amount)."""


async def _capture(monkeypatch, target: str) -> dict:
    captured = {}

    async def fake(org_id, inv, paid_amount_cents, lines_payload):
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
