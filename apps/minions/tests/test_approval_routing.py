"""HR plan phase 1: a claim goes to the nearest person up the reporting
line whose limit covers it, else the owners and admins; they're told;
a rejection says why and the claimant can fix it and send it again;
a payout says how it was paid."""

import pytest
from friday_common.access import Approvers
from friday_common.testing import make_principal

LIMITS = {"team_leader": 200_000, "branch_manager": 2_000_000}
LINE = (
    {"user_id": "u-tom", "role": "team_leader", "name": "Tom", "email": "tom@x.test"},
    {"user_id": "u-bea", "role": "branch_manager", "name": "Bea", "email": "bea@x.test"},
)
TOP = (
    {"user_id": "u-olive", "role": "owner", "name": "Olive", "email": "olive@x.test"},
    {"user_id": "u-ade", "role": "admin", "name": "Ade", "email": "ade@x.test"},
)


def test_pick_walks_up_until_a_limit_covers_it():
    who = Approvers(limits=LIMITS, chain=LINE, top=TOP)
    assert who.pick(150_000)["user_id"] == "u-tom"
    assert who.pick(500_000)["user_id"] == "u-bea"
    assert who.pick(5_000_000) is None  # owners and admins
    staff_boss = Approvers(limits=LIMITS, chain=({"user_id": "u-x", "role": "member"}, TOP[1]), top=TOP)
    assert staff_boss.pick(10)["user_id"] == "u-ade"  # staff decide nothing; an admin anything


def _person(principal, user_id, email, role="member", team=()):
    p = make_principal(org_id=principal.org_id, role=role, email=email, team=team)
    return p.__class__(**{**p.__dict__, "user_id": user_id})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake)

    async def line(_org, user_id):
        return Approvers(limits=LIMITS, chain=LINE if user_id == "u-sam" else (), top=TOP)

    monkeypatch.setattr("app.main.approvers_for", line)
    return sent


async def _setup(client, as_principal, principal):
    as_principal(make_principal(org_id=principal.org_id, role="admin"))
    for name in ("Sam", "Tom", "Bea"):
        await client.post("/employees", json={"name": name, "email": f"{name.lower()}@x.test"})
    for uid, email in (("u-sam", "sam@x.test"), ("u-tom", "tom@x.test"), ("u-bea", "bea@x.test")):
        as_principal(_person(principal, uid, email))
        assert (await client.get("/me/wallet")).status_code == 200  # claims the employee row


async def test_a_claim_waits_on_the_right_person_who_is_told(client, as_principal, principal, events):
    await _setup(client, as_principal, principal)
    as_principal(_person(principal, "u-sam", "sam@x.test"))
    small = (await client.post("/expense_claims", json={"description": "taxi", "amount_cents": 150_000})).json()
    big = (await client.post("/expense_claims", json={"description": "tyres", "amount_cents": 500_000})).json()
    huge = (await client.post("/expense_claims", json={"description": "fridge", "amount_cents": 9_000_000})).json()
    names = (small["waiting_on_name"], big["waiting_on_name"], huge["waiting_on_name"])
    assert names == ("Tom", "Bea", "an owner or admin")
    needed = [p for e, p in events if e == "minions.approval.needed"]
    assert [p["to_user_ids"] for p in needed] == [["u-tom"], ["u-bea"], ["u-olive", "u-ade"]]

    # Bea's inbox has only what waits on her; she may decide it even
    # though Sam isn't in her token's team or locations.
    as_principal(_person(principal, "u-bea", "bea@x.test", role="branch_manager"))
    assert [c["id"] for c in (await client.get("/expense_claims?waiting=true")).json()] == [big["id"]]
    r = await client.patch(f"/expense_claims/{big['id']}/status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["decided_by_name"] == "Bea" and r.json()["waiting_on_name"] == ""
    decided = [p for e, p in events if e == "minions.expense_claim.decided"]
    assert decided[-1]["to_user_ids"] == ["u-sam"] and decided[-1]["status"] == "approved"

    # Owners and admins see every waiting claim.
    as_principal(make_principal(org_id=principal.org_id, role="owner"))
    waiting = {c["id"] for c in (await client.get("/expense_claims?waiting=true")).json()}
    assert waiting == {small["id"], huge["id"]}


async def test_rejected_needs_a_reason_and_can_be_fixed_and_sent_again(client, as_principal, principal, events):
    await _setup(client, as_principal, principal)
    sam = _person(principal, "u-sam", "sam@x.test")
    as_principal(sam)
    claim = (await client.post("/expense_claims", json={"description": "taxi", "amount_cents": 150_000})).json()
    as_principal(_person(principal, "u-tom", "tom@x.test", role="team_leader", team=("u-sam",)))

    def decide(body):
        return client.patch(f"/expense_claims/{claim['id']}/status", json=body)

    assert (await decide({"status": "rejected"})).status_code == 422
    r = await decide({"status": "rejected", "note": "photo is blurry"})
    assert r.status_code == 200 and r.json()["decision_note"] == "photo is blurry"

    assert (await client.post(f"/expense_claims/{claim['id']}/resend", json={})).status_code == 403  # not Tom's
    as_principal(sam)
    r = await client.post(f"/expense_claims/{claim['id']}/resend", json={"amount_cents": 400_000})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "submitted" and body["decision_note"] == ""
    assert body["amount_cents"] == 400_000 and body["waiting_on_name"] == "Bea"  # bigger now: past Tom's limit
    assert (await client.post(f"/expense_claims/{claim['id']}/resend", json={})).status_code == 400  # waiting


async def test_paid_by_mpesa_records_the_code_and_tells_the_books(client, as_principal, principal, events):
    await _setup(client, as_principal, principal)
    as_principal(_person(principal, "u-sam", "sam@x.test"))
    claim = (await client.post("/expense_claims", json={"description": "taxi", "amount_cents": 1_000})).json()
    as_principal(make_principal(org_id=principal.org_id, role="admin"))
    assert (await client.patch(f"/expense_claims/{claim['id']}/status", json={"status": "approved"})).status_code == 200

    def pay(body):
        return client.post(f"/expense_claims/{claim['id']}/pay", json=body)

    assert (await pay({"method": "mpesa"})).status_code == 422  # needs the code
    r = await pay({"method": "mpesa", "reference": "SKD12AB3CD"})
    assert r.status_code == 200
    assert r.json()["paid_method"] == "mpesa" and r.json()["paid_reference"] == "SKD12AB3CD"
    [paid] = [p for e, p in events if e == "minions.expense_claim.paid"]
    assert paid["method"] == "mpesa" and paid["to_user_ids"] == ["u-sam"]
