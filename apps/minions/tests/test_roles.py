"""Plan section 12, step 2 in Minions: who sees which staff, pay and
claims, and who may decide a claim."""

import uuid

from app.models import Employee
from friday_common.db import _session_factory, set_org_context
from friday_common.testing import make_principal


def _admin(principal):
    return make_principal(org_id=principal.org_id, role="admin")


async def _staff(client, as_principal, principal, people):
    """Creates employees as an admin; `people` is [(name, user_id, pay)]."""
    as_principal(_admin(principal))
    out = {}
    for name, _uid, pay in people:
        e = (
            await client.post(
                "/employees", json={"name": name, "email": f"{name.lower()}@x.test", "pay_rate_cents": pay}
            )
        ).json()
        out[name] = e
    # Their Friday accounts: what their first sign-in would have claimed.
    async with _session_factory()() as session:
        await set_org_context(session, principal.org_id)
        for name, user_id, _ in people:
            row = await session.get(Employee, uuid.UUID(out[name]["id"]))
            row.user_id = user_id
        await session.commit()
    return out


async def test_a_team_leader_sees_their_team_without_pay(client, as_principal, principal):
    await _staff(client, as_principal, principal, [("Tom", "u-tom", 50000), ("Sam", "u-sam", 30000), ("Ann", "u-ann", 40000)])
    lead = make_principal(org_id=principal.org_id, role="team_leader", team=("u-sam",))
    lead = lead.__class__(**{**lead.__dict__, "user_id": "u-tom"})
    as_principal(lead)
    rows = (await client.get("/employees")).json()
    by = {r["name"]: r for r in rows}
    assert set(by) == {"Tom", "Sam"}  # themselves and their team, not Ann
    assert by["Sam"]["pay_rate_cents"] is None and by["Tom"]["pay_rate_cents"] == 50000  # own pay only

    as_principal(_admin(principal))
    assert all(r["pay_rate_cents"] is not None for r in (await client.get("/employees")).json())


async def test_a_branch_manager_sees_their_locations(client, as_principal, principal, monkeypatch):
    await _staff(client, as_principal, principal, [("Bea", "u-bea", 0), ("Sam", "u-sam", 0), ("Ann", "u-ann", 0)])

    async def at_westlands(scope, org_id):
        assert scope.kind == "loc" and scope.locs == ("L-west",)
        return {"u-bea", "u-sam"}

    monkeypatch.setattr("app.main.people_in", at_westlands)
    boss = make_principal(org_id=principal.org_id, role="branch_manager", locs=("L-west",))
    as_principal(boss)
    assert {r["name"] for r in (await client.get("/employees")).json()} == {"Bea", "Sam"}


async def _claim(client, as_principal, principal, user_id, email, amount):
    me = make_principal(org_id=principal.org_id, email=email)
    me = me.__class__(**{**me.__dict__, "user_id": user_id})
    as_principal(me)
    return (await client.post("/expense_claims", json={"description": "Fuel", "amount_cents": amount})).json()


async def test_claims_are_decided_by_someone_over_the_claimant_within_their_limit(client, as_principal, principal):
    await _staff(client, as_principal, principal, [("Tom", "u-tom", 0), ("Sam", "u-sam", 0), ("Ann", "u-ann", 0)])
    small = await _claim(client, as_principal, principal, "u-sam", "sam@x.test", 150000)
    big = await _claim(client, as_principal, principal, "u-sam", "sam@x.test", 500000)
    anns = await _claim(client, as_principal, principal, "u-ann", "ann@x.test", 1000)
    toms = await _claim(client, as_principal, principal, "u-tom", "tom@x.test", 1000)

    lead = make_principal(org_id=principal.org_id, role="team_leader", team=("u-sam",))
    lead = lead.__class__(**{**lead.__dict__, "user_id": "u-tom"})
    as_principal(lead)
    # Their team's claims, and their own; not Ann's.
    seen = {c["id"] for c in (await client.get("/expense_claims")).json()}
    assert seen == {small["id"], big["id"], toms["id"]}

    decide = lambda c: client.patch(f"/expense_claims/{c['id']}/status", json={"status": "approved"})
    assert (await decide(small)).status_code == 200
    r = await decide(big)
    assert r.status_code == 403 and "approval limit" in r.json()["detail"]
    assert (await decide(anns)).status_code == 403  # not their team
    r = await decide(toms)
    assert r.status_code == 403 and "own claim" in r.json()["detail"]

    # Staff see only their own and decide nothing.
    sam = make_principal(org_id=principal.org_id, email="sam@x.test")
    sam = sam.__class__(**{**sam.__dict__, "user_id": "u-sam"})
    as_principal(sam)
    assert {c["id"] for c in (await client.get("/expense_claims")).json()} == {small["id"], big["id"]}
    assert (await decide(anns)).status_code == 403

    as_principal(_admin(principal))
    assert (await decide(big)).status_code == 200  # no limit for admins
