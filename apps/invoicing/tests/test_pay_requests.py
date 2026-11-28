"""Pay requests: sending an invoice asks the business's provider (Paystack,
Stripe or Pesapal, the same way) for the money; it counts only when the
provider's own status says paid, checked on a schedule; a new request or a
void cancels the last. Never calls a provider."""

import hashlib
import hmac
import json

import pytest

import app.pay_requests as pr


@pytest.fixture
def provider(monkeypatch):
    state = {"name": "paystack", "paid": {}, "made": [], "cancelled": [], "checks": []}

    class Fake:
        consumer_key = "ck"

        async def create_pay_request(self, amount_cents, currency, **kw):
            ref = f"PRQ_{len(state['made']) + 1}"
            state["made"].append((ref, amount_cents, currency, kw["email"]))
            state.setdefault("ipn_ids", []).append(kw["metadata"].get("ipn_id"))
            return {"ref": ref, "url": "https://pay.example/" + ref if state["name"] == "pesapal" else "",
                    "ipn_id": kw["metadata"].get("ipn_id") or "IPN_1"}

        async def pay_request_status(self, ref):
            amount = state["paid"].get(ref, 0)
            return {"paid": bool(amount), "amount": amount, "currency": "KES" if amount else ""}

        async def cancel_pay_request(self, ref):
            state["cancelled"].append(ref)

    async def provider_for(org_id, name=""):
        return None if state["name"] == "" else (name or state["name"], Fake())

    async def publish(event_type, org_id, payload, **kw):
        if event_type == "invoicing.pay_request.check":
            state["checks"].append((payload, kw.get("deliver_at")))

    monkeypatch.setattr(pr, "provider_for", provider_for)
    monkeypatch.setattr(pr, "publish_event", publish)
    return state


async def _sent_invoice(client, email="ann@example.com"):
    customer = (await client.post("/customers", json={"name": "Ann", "email": email})).json()
    inv = (await client.post("/invoices", json={"customer_id": customer["id"], "currency": "KES",
                                                "lines": [{"description": "Consulting", "quantity": 1, "unit_price_cents": 5000}]})).json()
    return (await client.patch(f"/invoices/{inv['id']}/status", json={"status": "sent"})).json()


async def _check(client, kernel_auth_header, principal, payload, n):
    body = {"id": f"evt-{n}", "org_id": principal.org_id, "type": "invoicing.pay_request.check", "payload": payload}
    r = await client.post("/internal/webhooks/pay-request-check", headers=kernel_auth_header, json=body)
    assert r.status_code == 204, r.text


async def test_sending_requests_the_money_and_the_check_settles_it(client, provider, kernel_auth_header, principal):
    inv = await _sent_invoice(client)
    assert inv["pay_request_provider"] == "paystack"
    assert provider["made"] == [("PRQ_1", 5000, "KES", "ann@example.com")]
    [(first, _)] = provider["checks"]

    # Not paid yet: asked again later.
    await _check(client, kernel_auth_header, principal, first, 1)
    assert [c[0]["attempt"] for c in provider["checks"]] == [0, 1]

    provider["paid"]["PRQ_1"] = 5000
    await _check(client, kernel_auth_header, principal, provider["checks"][-1][0], 2)
    out = (await client.get(f"/invoices/{inv['id']}")).json()
    assert out["status"] == "paid" and [p["method"] for p in out["payments"]] == ["card"]
    assert len(provider["checks"]) == 2  # settled: no more checks
    # A repeat check records nothing twice.
    await _check(client, kernel_auth_header, principal, first, 3)
    assert len((await client.get(f"/invoices/{inv['id']}")).json()["payments"]) == 1


async def test_a_new_request_or_a_void_cancels_the_last(client, provider, kernel_auth_header, principal):
    inv = await _sent_invoice(client)
    r = await client.post(f"/invoices/{inv['id']}/pay-request")
    assert r.status_code == 200 and provider["cancelled"] == ["PRQ_1"]
    # The replaced request's check stops; paying it later records nothing.
    provider["paid"]["PRQ_1"] = 5000
    await _check(client, kernel_auth_header, principal, provider["checks"][0][0], 1)
    assert (await client.get(f"/invoices/{inv['id']}")).json()["status"] == "sent"
    await client.patch(f"/invoices/{inv['id']}/status", json={"status": "void"})
    assert provider["cancelled"] == ["PRQ_1", "PRQ_2"]


async def test_pesapals_page_goes_in_the_invoice_and_no_provider_means_no_request(client, provider):
    provider["name"] = "pesapal"
    inv = await _sent_invoice(client)
    assert inv["pay_request_url"] == "https://pay.example/PRQ_1"
    provider["name"] = ""
    plain = await _sent_invoice(client, email="bob@example.com")
    assert plain["status"] == "sent" and plain["pay_request_provider"] == ""
    r = await client.post(f"/invoices/{plain['id']}/pay-request")
    assert r.status_code == 400 and "connect" in r.json()["detail"]
    no_email = await _sent_invoice(client, email="")
    assert no_email["pay_request_provider"] == ""


async def test_pesapal_requests_reuse_the_businesss_ipn_id(client, provider, monkeypatch):
    monkeypatch.setattr(pr, "webhook_url", lambda name: "https://shop.example/kernel/external/webhooks/pesapal")
    provider["name"] = "pesapal"
    await _sent_invoice(client)
    await _sent_invoice(client, email="bob@example.com")
    assert provider["ipn_ids"] == [None, "IPN_1"]  # registered once, then reused


async def test_paystacks_paymentrequest_success_settles_at_once(client, provider, kernel_auth_header, principal, monkeypatch):
    secret = "sk_test_abc"

    async def config(org_id, name):
        assert org_id == principal.org_id
        return {"secret_key": secret}

    monkeypatch.setattr("app.webhooks.get_integration_config", config)
    inv = await _sent_invoice(client)
    provider["paid"]["PRQ_1"] = 5000
    # Paystack sends back the metadata Friday gave the request (a JSON string).
    meta = json.dumps({"org_id": principal.org_id, "invoice_id": inv["id"]})
    raw = json.dumps({"event": "paymentrequest.success", "data": {"request_code": "PRQ_1", "metadata": meta}}).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    headers = {"x-paystack-signature": sig, "content-type": "application/json"}
    forged = dict(headers, **{"x-paystack-signature": "0" * 128})
    assert (await client.post("/external/webhooks/paystack", content=raw, headers=forged)).status_code == 400
    assert (await client.get(f"/invoices/{inv['id']}")).json()["status"] == "sent"

    r = await client.post("/external/webhooks/paystack", content=raw, headers=headers)
    assert r.status_code == 200, r.text
    assert (await client.get(f"/invoices/{inv['id']}")).json()["status"] == "paid"
    # The scheduled check that comes later finds it settled and stops.
    [(first, _)] = provider["checks"]
    await _check(client, kernel_auth_header, principal, first, 1)
    assert len(provider["checks"]) == 1
    assert len((await client.get(f"/invoices/{inv['id']}")).json()["payments"]) == 1
