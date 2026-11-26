"""Spending plan part C: petty cash. A float per location, one holder; a
petty cash claim is the slip (at most the policy's most), confirmed by the
holder once approved; someone other than the holder tops it up; a count
books what's over or short."""

import pytest
from friday_common.testing import make_principal


def _person(principal, user_id, email, role="member"):
    p = make_principal(org_id=principal.org_id, role=role, email=email)
    return p.__class__(**{**p.__dict__, "user_id": user_id})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    return sent


async def test_a_float_its_slips_top_ups_and_counts(client, as_principal, principal, events):
    admin = _person(principal, "u-boss-pc", "boss-pc@x.test", "admin")
    jane = _person(principal, "u-jane-pc", "jane-pc@x.test")
    as_principal(admin)
    for name, email in (("Boss", admin.email), ("Jane", jane.email)):
        await client.post("/employees", json={"name": name, "email": email})
    for who in (admin, jane):
        as_principal(who)
        await client.get("/me/wallet")  # claims the staff row
    as_principal(admin)
    f = (await client.post("/petty_cash", json={"name": "Shop petty cash", "location_id": "loc-1", "holder_user_id": jane.user_id})).json()
    assert (f["float_cents"], f["holder_name"], f["balance_cents"]) == (1_000_000, "Jane", 0)  # Standard: 10,000
    again = await client.post("/petty_cash", json={"name": "Again", "location_id": "loc-1", "holder_user_id": jane.user_id})
    assert again.status_code == 409  # one per location
    mine = (await client.post("/petty_cash", json={"name": "Office", "location_id": "loc-2", "holder_user_id": admin.user_id})).json()
    assert (await client.post(f"/petty_cash/{mine['id']}/top_up", json={"method": "cash"})).status_code == 403  # not the holder
    r = await client.post(f"/petty_cash/{f['id']}/top_up", json={"method": "mpesa", "reference": "SKX1"})
    assert r.status_code == 200 and r.json()["balance_cents"] == 1_000_000
    assert (await client.post(f"/petty_cash/{f['id']}/top_up", json={"method": "cash"})).status_code == 400  # full

    as_principal(jane)
    claim = lambda cents, fid=None: client.post("/expense_claims", json={  # noqa: E731
        "description": "Milk", "amount_cents": cents, "paid_from": "petty_cash", **({"float_id": fid} if fid else {})})
    assert (await claim(50_000)).status_code == 422  # two floats: say which
    assert (await claim(250_000, f["id"])).status_code == 422  # over 2,000 a slip
    slip = (await claim(50_000, f["id"])).json()
    assert slip["float_id"] == f["id"] and slip["reimburse"] is False
    # Others see whose it is, not what's in it.
    assert [x["balance_cents"] for x in (await client.get("/petty_cash")).json() if x["id"] == mine["id"]] == [None]

    as_principal(admin)
    await client.patch(f"/expense_claims/{slip['id']}/status", json={"status": "approved"})
    r = await client.post(f"/expense_claims/{slip['id']}/pay", json={"method": "cash"})
    assert r.status_code == 400 and "holder" in r.json()["detail"]

    as_principal(jane)
    assert [c["id"] for c in (await client.get("/petty_cash/slips")).json()] == [slip["id"]]
    r = await client.post(f"/petty_cash/slips/{slip['id']}/confirm")
    assert r.status_code == 200 and (r.json()["status"], r.json()["paid_method"]) == ("paid", "petty_cash")
    [paid] = [p for e, p in events if e == "minions.expense_claim.paid"]
    assert (paid["method"], paid["amount_cents"]) == ("petty_cash", 50_000)

    # 9,500 should be there; she counts 9,400.
    assert (await client.post(f"/petty_cash/{f['id']}/count", json={"counted_cents": 940_000})).status_code == 422
    r = await client.post(f"/petty_cash/{f['id']}/count", json={"counted_cents": 940_000, "note": "Change given wrong"})
    assert r.json()["balance_cents"] == 940_000
    moved = [p for e, p in events if e == "minions.petty_cash.moved"]
    assert [(m["kind"], m["amount_cents"]) for m in moved] == [("top_up", 1_000_000), ("count", -10_000)]
    as_principal(admin)
    r = await client.post(f"/petty_cash/{f['id']}/top_up", json={"method": "cash"})
    assert r.json()["balance_cents"] == 1_000_000 and r.json()["moves"][0]["amount_cents"] == 60_000
