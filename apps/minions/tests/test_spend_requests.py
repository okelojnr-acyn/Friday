"""Spending plan part B: ask first above the role's amount (and always for
trips); the claim carries the approval and is flagged past the tolerance;
emergencies are allowed with a reason, go one level higher and need a
receipt; a trip's cash advance is settled against its claims."""

import pytest
from friday_common.access import STANDARD_SPENDING, Approvers
from friday_common.testing import make_principal

import app.main

REAL_RECEIPT_RULE = app.main._receipt_problem
PNG = b"\x89PNG\r\n\x1a\nfake"


def _staff(principal):
    p = make_principal(org_id=principal.org_id, email="jane@example.com")
    return p.__class__(**{**p.__dict__, "user_id": "u-jane"})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    async def standard(_org):
        return dict(STANDARD_SPENDING)  # Standard: staff ask first above 2,000

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    monkeypatch.setattr("app.main.spending_policy", standard)
    return sent


async def _jane(client, as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    await client.post("/employees", json={"name": "Jane", "email": "jane@example.com", "pay_rate_cents": 6_000_000})
    as_principal(_staff(principal))
    return admin


async def test_ask_first_then_claim_against_it(client, as_principal, principal, events):
    admin = await _jane(client, as_principal, principal)
    small = await client.post("/expense_claims", json={"description": "Airtime", "amount_cents": 150_000})
    assert small.status_code == 201  # under 2,000: no need to ask
    r = await client.post("/expense_claims", json={"description": "Paint", "amount_cents": 500_000})
    assert r.status_code == 422 and "asking first" in r.json()["detail"]

    req = (await client.post("/spend_requests", json={
        "description": "Paint for the shopfront", "amount_cents": 500_000, "category": "supplies",
        "for_kind": "project", "for_id": "p-1", "for_label": "Shopfront"})).json()
    assert req["status"] == "submitted" and req["waiting_on_name"] == "an owner or admin"
    assert [p["kind"] for e, p in events if e == "minions.approval.needed"][-1] == "spend_request"
    r = await client.post("/expense_claims", json={"description": "Paint", "amount_cents": 500_000, "request_id": req["id"]})
    assert r.status_code == 400  # not approved yet

    as_principal(admin)
    assert (await client.patch(f"/spend_requests/{req['id']}/status", json={"status": "approved"})).status_code == 200
    as_principal(_staff(principal))
    assert [r["id"] for r in (await client.get("/spend_requests?mine=true&open=true")).json()] == [req["id"]]
    c = (await client.post("/expense_claims", json={"description": "Paint", "amount_cents": 520_000, "request_id": req["id"]})).json()
    assert (c["for_kind"], c["for_label"], c["flag"]) == ("project", "Shopfront", "")  # within 10%
    over = (await client.post("/expense_claims", json={"description": "More paint", "amount_cents": 100_000, "request_id": req["id"]})).json()
    assert over["flag"] == "24% over the approved 5,000"


async def test_an_emergency_goes_one_higher_and_needs_its_receipt(client, as_principal, principal, events, monkeypatch):
    monkeypatch.setattr("app.main._receipt_problem", REAL_RECEIPT_RULE)
    line = ({"user_id": "u-tom", "role": "team_leader", "name": "Tom"},
            {"user_id": "u-bea", "role": "branch_manager", "name": "Bea"})

    async def approvers(_org, _user):
        return Approvers(limits={"team_leader": 2_000_000, "branch_manager": 5_000_000}, chain=line, top=())

    monkeypatch.setattr("app.main.approvers_for", approvers)
    admin = await _jane(client, as_principal, principal)
    c = (await client.post("/expense_claims", json={
        "description": "Burst pipe repair", "amount_cents": 400_000, "category": "repairs",
        "emergency_reason": "Water flooding the store at night"})).json()
    assert (c["flag"], c["waiting_on_name"]) == ("not asked first", "Bea")  # Tom skipped
    as_principal(admin)
    r = await client.patch(f"/expense_claims/{c['id']}/status", json={"status": "approved"})
    assert r.status_code == 400 and "receipt" in r.json()["detail"]
    # Guss sends money already spent: flagged, never refused.
    as_principal(_staff(principal))
    g = await client.post("/expense_claims", json={"description": "fuel (Guss 0a1b2c3d)", "amount_cents": 900_000})
    assert g.status_code == 201 and g.json()["flag"] == "not asked first (from Guss)"


async def test_a_trip_with_an_advance_is_settled(client, as_principal, principal, events):
    admin = await _jane(client, as_principal, principal)
    # A trip claim without an approved trip isn't taken.
    r = await client.post("/expense_claims", json={"description": "Bus", "amount_cents": 50_000, "for_kind": "trip", "for_id": "x"})
    assert r.status_code == 422
    bad = await client.post("/spend_requests", json={"kind": "trip", "description": "Supplier visit", "amount_cents": 1_000_000,
                                                      "destination": "Nakuru", "starts_on": "2026-12-02", "ends_on": "2026-12-01"})
    assert bad.status_code == 422
    trip = (await client.post("/spend_requests", json={
        "kind": "trip", "description": "Supplier visit", "amount_cents": 1_000_000, "advance_cents": 800_000,
        "destination": "Nakuru", "starts_on": "2026-12-01", "ends_on": "2026-12-02"})).json()
    assert trip["for_kind"] == "trip"
    as_principal(admin)
    await client.patch(f"/spend_requests/{trip['id']}/status", json={"status": "approved"})
    r = await client.post(f"/spend_requests/{trip['id']}/advance", json={"method": "cash"})
    assert r.status_code == 200 and r.json()["advance_paid_at"]
    assert [p["amount_cents"] for e, p in events if e == "minions.trip_advance.paid"] == [800_000]

    as_principal(_staff(principal))
    claims = [(await client.post("/expense_claims", json={
        "description": d, "amount_cents": a, "for_kind": "trip", "for_id": trip["id"]})).json() for d, a in (("Bus", 150_000), ("Hotel", 450_000))]
    assert all(c["request_id"] == trip["id"] and c["for_label"] == "Nakuru" for c in claims)

    as_principal(admin)
    assert (await client.post(f"/spend_requests/{trip['id']}/settle", json={"method": "payroll"})).status_code == 400  # still waiting
    for c in claims:
        await client.patch(f"/expense_claims/{c['id']}/status", json={"status": "approved"})
    r = await client.post(f"/expense_claims/{claims[0]['id']}/pay", json={"method": "cash"})
    assert r.status_code == 400 and "advance" in r.json()["detail"]
    r = await client.post(f"/spend_requests/{trip['id']}/settle", json={"method": "payroll"})
    assert r.status_code == 200 and (r.json()["status"], r.json()["spent_cents"]) == ("closed", 600_000)
    [settled] = [p for e, p in events if e == "minions.trip.settled"]
    assert (settled["advance_cents"], settled["spent_cents"], settled["method"]) == (800_000, 600_000, "payroll")
    as_principal(_staff(principal))
    mine = {c["id"]: c for c in (await client.get("/expense_claims?mine=true")).json()}
    assert all(mine[c["id"]]["status"] == "paid" and mine[c["id"]]["paid_method"] == "advance" for c in claims)
    # The 2,000 left comes off the next pay.
    [adv] = (await client.get("/salary_advances?mine=true")).json()
    assert (adv["amount_cents"], adv["status"]) == (200_000, "paid")
