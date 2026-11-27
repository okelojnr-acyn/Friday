"""Roadmap item 8: a large manual journal entry posted by an admin waits
as pending until an owner posts it; owners post their own; small ones
and entries the apps book never wait."""

import pytest
from friday_common.testing import make_principal



async def _account_id(client, code: str) -> str:
    accounts = (await client.get("/accounts")).json()
    return next(a["id"] for a in accounts if a["code"] == code)


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    async def read(_org):
        return {"manual_entry_ask_above": 5_000_000}  # 50,000.00

    monkeypatch.setattr("app.main.spending_policy", read)


async def entry(client, cents):
    cash = await _account_id(client, "1010")
    equity = await _account_id(client, "3000")
    r = await client.post(
        "/journal_entries",
        json={"entry_date": "2026-11-27", "memo": "Owner put money in", "lines": [{"account_id": cash, "debit_cents": cents}, {"account_id": equity, "credit_cents": cents}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_a_large_admin_entry_waits_for_an_owner(client, principal, as_principal):
    big = await entry(client, 6_000_000)
    post = lambda i: client.patch(f"/journal_entries/{i}/status", json={"status": "posted"})  # noqa: E731
    assert (await post(big)).json()["status"] == "pending"
    assert (await post(big)).status_code == 403  # the admin can't push it through

    small = await entry(client, 100_000)
    assert (await post(small)).json()["status"] == "posted"

    owner = make_principal(role="owner", org_id=principal.org_id)
    as_principal(owner)
    assert (await post(big)).json()["status"] == "posted"
    own_big = await entry(client, 9_000_000)
    assert (await post(own_big)).json()["status"] == "posted"


async def test_pending_is_set_by_the_rule_not_by_hand(client):
    e = await entry(client, 100)
    r = await client.patch(f"/journal_entries/{e}/status", json={"status": "pending"})
    assert r.status_code == 422
