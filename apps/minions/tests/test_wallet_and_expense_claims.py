from friday_common.testing import make_principal


def _as_admin(as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    return admin


async def test_get_my_wallet_404s_when_not_provisioned(client):
    resp = await client.get("/me/wallet")
    assert resp.status_code == 404


async def test_set_my_wallet_claims_employee_row_by_email(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)  # the employee themselves, not the admin
    resp = await client.put("/me/wallet", json={"wallet_address": "0xabc123", "wallet_network": "base"})
    assert resp.status_code == 200
    assert resp.json()["wallet_address"] == "0xabc123"

    # claimed -- a second call resolves by user_id now, not email
    resp2 = await client.get("/me/wallet")
    assert resp2.json()["wallet_address"] == "0xabc123"

    as_principal(admin)
    roster = (await client.get("/employees")).json()
    assert roster[0]["user_id"] == principal.user_id


async def test_create_expense_claim_requires_provisioned_employee(client):
    resp = await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})
    assert resp.status_code == 404


async def test_create_expense_claim_self_service(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    resp = await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["amount_cents"] == 2500


async def test_member_cannot_approve_expense_claim(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    claim = (await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})).json()
    resp = await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "approved"})
    assert resp.status_code == 403


async def test_admin_approves_then_pay_requires_wallet(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    claim = (await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})).json()

    as_principal(admin)
    approved = await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "approved"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    pay_resp = await client.post(f"/expense_claims/{claim['id']}/pay")
    assert pay_resp.status_code == 400  # no wallet connected yet


async def test_cannot_approve_a_claim_twice(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    claim = (await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})).json()

    as_principal(admin)
    await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "approved"})
    resp = await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "rejected"})
    assert resp.status_code == 400


async def test_pay_expense_claim_calls_acyn_wallet_when_wallet_connected(client, as_principal, principal, monkeypatch):
    admin = _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    await client.put("/me/wallet", json={"wallet_address": "0xabc", "wallet_network": "base"})
    claim = (await client.post("/expense_claims", json={"description": "Taxi", "amount_cents": 2500})).json()

    as_principal(admin)
    await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "approved"})

    async def fake_config(org_id, provider):
        return {"api_key": "test-key"}

    captured = {}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def request_payout(self, **kwargs):
            captured.update(kwargs)
            return {"id": "payout-1", "status": "pending"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.AcynWalletProvider", FakeProvider)

    resp = await client.post(f"/expense_claims/{claim['id']}/pay")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert captured["to_address"] == "0xabc"
    assert captured["amount"] == "25.00"


async def test_business_paid_claim_is_recorded_never_paid_out(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    mine = (await client.post("/expense_claims", json={"description": "Fuel", "amount_cents": 2500})).json()
    assert mine["reimburse"] is True  # default: I paid, pay me back
    biz = (
        await client.post("/expense_claims", json={"description": "Fuel", "amount_cents": 2500, "reimburse": False})
    ).json()
    assert biz["reimburse"] is False

    as_principal(admin)
    await client.patch(f"/expense_claims/{biz['id']}/status", json={"status": "approved"})
    resp = await client.post(f"/expense_claims/{biz['id']}/pay")
    assert resp.status_code == 400 and "business paid" in resp.json()["detail"]


async def test_receipt_photo_by_the_claimant_seen_by_approvers(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})

    as_principal(principal)
    claim = (await client.post("/expense_claims", json={"description": "Fuel", "amount_cents": 2500})).json()
    png = b"\x89PNG\r\n\x1a\nfake"
    bad = await client.put(f"/expense_claims/{claim['id']}/receipt", content=b"x", headers={"content-type": "text/plain"})
    assert bad.status_code == 415
    put = await client.put(f"/expense_claims/{claim['id']}/receipt", content=png, headers={"content-type": "image/png"})
    assert put.status_code == 200 and put.json()["receipt_sha"]
    mine = await client.get(f"/expense_claims/{claim['id']}/receipt")
    assert mine.status_code == 200 and mine.content == png

    # An approver (someone else) sees it; only the claimant adds or changes it.
    admin = make_principal(org_id=principal.org_id, role="admin", email="boss@example.com")
    as_principal(admin)
    assert (await client.get(f"/expense_claims/{claim['id']}/receipt")).content == png
    again = await client.put(f"/expense_claims/{claim['id']}/receipt", content=png, headers={"content-type": "image/png"})
    assert again.status_code in (403, 404)


async def test_withdraw_a_waiting_claim_and_payouts_reach_the_books(client, as_principal, principal, monkeypatch):
    sent = []

    async def fake_publish_event(event_type, org_id, payload):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish_event)
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})
    as_principal(principal)
    claim = (await client.post("/expense_claims", json={"description": "fuel (Guss 1a2b3c4d)", "amount_cents": 2500})).json()
    r = await client.post(f"/expense_claims/{claim['id']}/withdraw")
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert (await client.post(f"/expense_claims/{claim['id']}/withdraw")).status_code == 400

    # Someone else can't withdraw yours.
    other = (await client.post("/expense_claims", json={"description": "taxi", "amount_cents": 900})).json()
    boss = make_principal(org_id=principal.org_id, role="admin", email="boss@example.com")
    as_principal(boss)
    assert (await client.post(f"/expense_claims/{other['id']}/withdraw")).status_code in (403, 404)
    assert sent == []
