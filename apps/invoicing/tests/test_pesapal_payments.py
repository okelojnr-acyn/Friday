"""Pesapal POS checkout: starting a hosted order (main.py's
pay_with_pesapal) and the IPN webhook that actually marks the sale paid
(webhooks.py's pesapal_webhook). Never hits the real Pesapal API --
PesapalProvider is monkeypatched with a fake standing in for the HTTP
calls friday_common/integrations/pesapal.py makes.
"""

import types


def _settings_with_public_url(url="http://localhost:8002"):
    return types.SimpleNamespace(app_public_url=url)


async def _pesapal_sale_body(cents=1000):
    return {"lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": cents}], "amount_cents": cents}


async def test_pay_with_pesapal_requires_connected_pesapal(client):
    resp = await client.post("/pos/sales/pay-with-pesapal", json=await _pesapal_sale_body())
    assert resp.status_code == 400


async def test_pay_with_pesapal_requires_app_public_url(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.get_settings", lambda: _settings_with_public_url(""))

    resp = await client.post("/pos/sales/pay-with-pesapal", json=await _pesapal_sale_body())
    assert resp.status_code == 500


async def test_pay_with_pesapal_creates_pending_invoice_and_returns_redirect(client, principal, monkeypatch):
    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FakePesapal:
        def __init__(self, config):
            self.config = config

        async def create_payment_intent(self, amount_cents, currency, metadata):
            assert amount_cents == 1000
            assert currency == "USD"
            assert metadata["merchant_reference"].startswith(f"{principal.org_id}:")
            assert metadata["callback_url"] == "http://localhost:8002/external/webhooks/pesapal"
            return {"id": "ot_123", "redirect_url": "https://pay.pesapal.com/checkout/ot_123"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.get_settings", lambda: _settings_with_public_url())
    monkeypatch.setattr("app.main.PesapalProvider", FakePesapal)

    resp = await client.post("/pos/sales/pay-with-pesapal", json=await _pesapal_sale_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["redirect_url"] == "https://pay.pesapal.com/checkout/ot_123"

    status = await client.get(f"/pos/sales/{body['invoice_id']}/status")
    assert status.json()["status"] == "pending"


async def test_pay_with_pesapal_voids_invoice_when_gateway_call_fails(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FailingPesapal:
        def __init__(self, config):
            pass

        async def create_payment_intent(self, amount_cents, currency, metadata):
            raise RuntimeError("Pesapal SubmitOrderRequest failed: boom")

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.get_settings", lambda: _settings_with_public_url())
    monkeypatch.setattr("app.main.PesapalProvider", FailingPesapal)

    resp = await client.post("/pos/sales/pay-with-pesapal", json=await _pesapal_sale_body())
    assert resp.status_code == 502


async def _start_pending_sale(client, principal, monkeypatch, cents=1000) -> str:
    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FakePesapal:
        def __init__(self, config):
            pass

        async def create_payment_intent(self, amount_cents, currency, metadata):
            return {"id": "ot_123", "redirect_url": "https://pay.pesapal.com/checkout/ot_123"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.get_settings", lambda: _settings_with_public_url())
    monkeypatch.setattr("app.main.PesapalProvider", FakePesapal)

    resp = await client.post("/pos/sales/pay-with-pesapal", json=await _pesapal_sale_body(cents))
    return resp.json()["invoice_id"]


async def test_pesapal_webhook_marks_invoice_paid_on_completed(client, principal, monkeypatch):
    invoice_id = await _start_pending_sale(client, principal, monkeypatch)

    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FakePesapal:
        def __init__(self, config):
            pass

        async def get_transaction_status(self, order_tracking_id):
            assert order_tracking_id == "ot_123"
            return "COMPLETED"

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.PesapalProvider", FakePesapal)

    resp = await client.get(
        "/external/webhooks/pesapal",
        params={"OrderTrackingId": "ot_123", "OrderMerchantReference": f"{principal.org_id}:{invoice_id}"},
    )
    assert resp.status_code == 200

    status = await client.get(f"/pos/sales/{invoice_id}/status")
    assert status.json()["status"] == "paid"


async def test_pesapal_webhook_voids_invoice_on_failed(client, principal, monkeypatch):
    invoice_id = await _start_pending_sale(client, principal, monkeypatch)

    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FakePesapal:
        def __init__(self, config):
            pass

        async def get_transaction_status(self, order_tracking_id):
            return "FAILED"

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.PesapalProvider", FakePesapal)

    await client.get(
        "/external/webhooks/pesapal",
        params={"OrderTrackingId": "ot_123", "OrderMerchantReference": f"{principal.org_id}:{invoice_id}"},
    )

    status = await client.get(f"/pos/sales/{invoice_id}/status")
    assert status.json()["status"] == "void"


async def test_pesapal_webhook_is_idempotent_once_resolved(client, principal, monkeypatch):
    invoice_id = await _start_pending_sale(client, principal, monkeypatch)

    calls = {"n": 0}

    async def fake_config(org_id, provider):
        return {"consumer_key": "ck", "consumer_secret": "cs"}

    class FakePesapal:
        def __init__(self, config):
            pass

        async def get_transaction_status(self, order_tracking_id):
            calls["n"] += 1
            return "COMPLETED"

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.PesapalProvider", FakePesapal)

    params = {"OrderTrackingId": "ot_123", "OrderMerchantReference": f"{principal.org_id}:{invoice_id}"}
    await client.get("/external/webhooks/pesapal", params=params)
    await client.get("/external/webhooks/pesapal", params=params)

    # Second delivery is a no-op once the invoice is no longer "pending"
    # -- IPN delivery can repeat, re-querying GetTransactionStatus (or
    # double-posting a Payment) on an already-resolved sale would be wrong.
    assert calls["n"] == 1


async def test_pesapal_webhook_rejects_malformed_merchant_reference(client):
    resp = await client.get(
        "/external/webhooks/pesapal",
        params={"OrderTrackingId": "ot_123", "OrderMerchantReference": "not-a-valid-reference"},
    )
    assert resp.status_code == 400
