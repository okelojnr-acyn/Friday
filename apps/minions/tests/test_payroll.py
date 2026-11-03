from friday_common.testing import make_principal


def _as_admin(as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    return admin


async def _employee_with_wallet(client, as_principal, principal, admin, email="jane@example.com", wallet="0xabc"):
    as_principal(admin)
    employee = (await client.post("/employees", json={"name": "Jane", "email": email, "pay_rate_cents": 300000})).json()
    member = make_principal(org_id=principal.org_id, email=email)
    as_principal(member)
    await client.put("/me/wallet", json={"wallet_address": wallet, "wallet_network": "base"})
    as_principal(admin)
    return employee


async def test_member_cannot_create_payroll_run(client):
    resp = await client.post(
        "/payroll_runs",
        json={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-01-31T00:00:00Z", "employee_ids": []},
    )
    assert resp.status_code == 403


async def test_create_payroll_run_requires_at_least_one_employee(client, as_principal, principal):
    _as_admin(as_principal, principal)
    resp = await client.post(
        "/payroll_runs",
        json={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-01-31T00:00:00Z", "employee_ids": []},
    )
    assert resp.status_code == 422


async def test_create_payroll_run_with_wallet_connected_employee(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    employee = await _employee_with_wallet(client, as_principal, principal, admin)

    resp = await client.post(
        "/payroll_runs",
        json={
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-01-31T00:00:00Z",
            "employee_ids": [employee["id"]],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["total_amount_cents"] == 300000
    assert body["lines"][0]["status"] == "pending"
    assert body["lines"][0]["to_address"] == "0xabc"


async def test_employee_without_wallet_is_blocked_in_payroll_run(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    employee = (await client.post("/employees", json={"name": "Bob", "email": "bob@example.com"})).json()

    resp = await client.post(
        "/payroll_runs",
        json={
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-01-31T00:00:00Z",
            "employee_ids": [employee["id"]],
        },
    )
    assert resp.json()["lines"][0]["status"] == "blocked"


async def test_payroll_run_approve_then_pay_queues_payouts(client, as_principal, principal, monkeypatch):
    admin = _as_admin(as_principal, principal)
    employee = await _employee_with_wallet(client, as_principal, principal, admin)

    run = (
        await client.post(
            "/payroll_runs",
            json={
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T00:00:00Z",
                "employee_ids": [employee["id"]],
            },
        )
    ).json()

    pay_before_approve = await client.post(f"/payroll_runs/{run['id']}/pay")
    assert pay_before_approve.status_code == 400

    approved = await client.post(f"/payroll_runs/{run['id']}/approve")
    assert approved.json()["status"] == "approved"

    captured = []

    async def fake_config(org_id, provider):
        return {"api_key": "test-key"}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def request_payout(self, **kwargs):
            captured.append(kwargs)
            return {"id": "payout-1", "status": "pending"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.AcynWalletProvider", FakeProvider)

    paid = await client.post(f"/payroll_runs/{run['id']}/pay")
    assert paid.status_code == 200
    body = paid.json()
    assert body["status"] == "paying"
    assert body["lines"][0]["status"] == "sent"
    assert body["lines"][0]["external_id"] == "payout-1"
    assert len(captured) == 1
    assert captured[0]["amount"] == "3000.00"


async def test_fiat_payroll_run_pay_is_not_implemented(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    employee = await _employee_with_wallet(client, as_principal, principal, admin)

    run = (
        await client.post(
            "/payroll_runs",
            json={
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T00:00:00Z",
                "payout_method": "fiat",
                "employee_ids": [employee["id"]],
            },
        )
    ).json()
    await client.post(f"/payroll_runs/{run['id']}/approve")

    resp = await client.post(f"/payroll_runs/{run['id']}/pay")
    assert resp.status_code == 501


async def test_refresh_status_confirms_and_marks_run_paid(client, as_principal, principal, monkeypatch):
    admin = _as_admin(as_principal, principal)
    employee = await _employee_with_wallet(client, as_principal, principal, admin)

    run = (
        await client.post(
            "/payroll_runs",
            json={
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T00:00:00Z",
                "employee_ids": [employee["id"]],
            },
        )
    ).json()
    await client.post(f"/payroll_runs/{run['id']}/approve")

    async def fake_config(org_id, provider):
        return {"api_key": "test-key"}

    class FakeProviderSend:
        def __init__(self, config):
            pass

        async def request_payout(self, **kwargs):
            return {"id": "payout-1", "status": "pending"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.AcynWalletProvider", FakeProviderSend)
    await client.post(f"/payroll_runs/{run['id']}/pay")

    class FakeProviderStatus:
        def __init__(self, config):
            pass

        async def get_payout_status(self, payout_id):
            assert payout_id == "payout-1"
            return {"status": "completed"}

    monkeypatch.setattr("app.main.AcynWalletProvider", FakeProviderStatus)
    resp = await client.post(f"/payroll_runs/{run['id']}/refresh-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lines"][0]["status"] == "confirmed"
    assert body["status"] == "paid"


async def test_my_payroll_shows_only_the_callers_own_lines(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    jane = await _employee_with_wallet(client, as_principal, principal, admin, email="jane@example.com", wallet="0xjane")
    bob = await _employee_with_wallet(client, as_principal, principal, admin, email="bob@example.com", wallet="0xbob")

    await client.post(
        "/payroll_runs",
        json={
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-01-31T00:00:00Z",
            "employee_ids": [jane["id"], bob["id"]],
        },
    )

    as_principal(make_principal(org_id=principal.org_id, email="jane@example.com"))
    resp = await client.get("/me/payroll")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["gross_amount_cents"] == 300000
    assert body[0]["run_status"] == "draft"
    assert body[0]["line_status"] == "pending"


async def test_my_payroll_is_empty_for_an_employee_with_no_runs(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    await _employee_with_wallet(client, as_principal, principal, admin)

    as_principal(make_principal(org_id=principal.org_id, email="jane@example.com"))
    resp = await client.get("/me/payroll")
    assert resp.status_code == 200
    assert resp.json() == []
