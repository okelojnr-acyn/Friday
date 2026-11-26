"""Spending plan part D: a request to buy before the order. Staff order a
draft straight away only up to their ask-first amount; above it they send
it for approval, someone else approves it within their limit (or sends it
back with a reason), then it's ordered. Suppliers never see a request."""

import pytest
from friday_common.access import STANDARD_SPENDING, Approvers
from friday_common.testing import make_principal


@pytest.fixture(autouse=True)
def standard(monkeypatch):
    async def policy(_org):
        return dict(STANDARD_SPENDING)  # staff: 2,000

    async def approvers(_org, _user):
        return Approvers(limits={"team_leader": 200_000, "branch_manager": 2_000_000}, chain=(), top=())

    monkeypatch.setattr("app.main.spending_policy", policy)
    monkeypatch.setattr("app.main.approvers_for", approvers)


def _as(principal, user_id, role):
    p = make_principal(org_id=principal.org_id, role=role, perms=("purchasing",))
    return p.__class__(**{**p.__dict__, "user_id": user_id})


async def test_a_request_to_buy_comes_before_the_order(client, as_principal, principal):
    buyer, leader, manager = _as(principal, "u-buy", "member"), _as(principal, "u-tl", "team_leader"), _as(principal, "u-bm", "branch_manager")
    as_principal(buyer)
    line = lambda cost: {"lines": [{"description": "Cement", "quantity": 10, "unit_cost_cents": cost}]}  # noqa: E731
    small = (await client.post("/purchase_orders", json=line(10_000))).json()  # 1,000
    big = (await client.post("/purchase_orders", json=line(100_000))).json()  # 10,000
    status = lambda po, s, note="": client.patch(f"/purchase_orders/{po['id']}/status", json={"status": s, "note": note})  # noqa: E731

    assert (await status(small, "ordered")).status_code == 200  # under 2,000: no need
    r = await status(big, "ordered")
    assert r.status_code == 403 and "approval" in r.json()["detail"]
    assert (await status(big, "requested")).json()["requested_by_name"] == buyer.email
    assert (await status(big, "approved")).status_code == 403  # not your own
    assert (await status(big, "ordered")).status_code == 400  # waiting

    as_principal(leader)
    r = await status(big, "approved")
    assert r.status_code == 403 and "limit" in r.json()["detail"]  # 10,000 > the leader's 2,000
    as_principal(manager)
    assert (await status(big, "draft")).status_code == 422  # say why
    back = (await status(big, "draft", "Get a second quote")).json()
    assert (back["status"], back["decision_note"]) == ("draft", "Get a second quote")

    as_principal(buyer)
    await status(big, "requested")
    as_principal(manager)
    assert (await status(big, "approved")).json()["decided_by_name"] == manager.email
    as_principal(buyer)
    assert (await status(big, "ordered")).status_code == 200
