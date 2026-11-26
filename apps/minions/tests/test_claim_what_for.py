"""Spending plan part A: every claim says what it was for and which money
paid it, and the receipt rule (receipts always; a reason only for small
amounts, a few times a year) holds at approval."""

from friday_common.testing import make_principal

import app.main

REAL_RECEIPT_RULE = app.main._receipt_problem  # conftest turns it off for other tests
PNG = b"\x89PNG\r\n\x1a\nfake"


async def _setup(client, as_principal, principal, monkeypatch):
    monkeypatch.setattr("app.main._receipt_problem", REAL_RECEIPT_RULE)
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})
    as_principal(principal)
    return admin


async def test_what_for_and_who_paid(client, as_principal, principal, monkeypatch):
    await _setup(client, as_principal, principal, monkeypatch)
    c = (await client.post("/expense_claims", json={
        "description": "Taxi to the supplier", "amount_cents": 50_000, "category": "transport",
        "for_kind": "task", "for_id": "t-1", "for_label": "Collect the paint order", "paid_from": "petty_cash",
    })).json()
    assert (c["for_kind"], c["for_label"], c["category"], c["paid_from"], c["reimburse"]) == (
        "task", "Collect the paint order", "transport", "petty_cash", False)
    # A task, project or vehicle must say which one.
    r = await client.post("/expense_claims", json={"description": "x", "amount_cents": 100, "for_kind": "project"})
    assert r.status_code == 422
    # Older apps (and Guss) send reimburse only: daily running, own money.
    old = (await client.post("/expense_claims", json={"description": "Airtime", "amount_cents": 100})).json()
    assert (old["for_kind"], old["paid_from"], old["reimburse"]) == ("daily", "own", True)


async def test_receipt_rule_at_approval(client, as_principal, principal, monkeypatch):
    admin = await _setup(client, as_principal, principal, monkeypatch)

    async def send(cents, reason=""):
        return (await client.post("/expense_claims", json={"description": "Lunch", "amount_cents": cents, "no_receipt_reason": reason})).json()

    big, nothing = await send(150_000), await send(5_000)
    small = [await send(5_000, "Market stall, no receipts") for _ in range(4)]
    with_photo = await send(150_000)
    await client.put(f"/expense_claims/{with_photo['id']}/receipt", content=PNG, headers={"content-type": "image/png"})

    as_principal(admin)
    approve = lambda c: client.patch(f"/expense_claims/{c['id']}/status", json={"status": "approved"})  # noqa: E731
    r = await approve(big)  # Standard: a receipt from 1,000 up
    assert r.status_code == 400 and "receipt is needed" in r.json()["detail"]
    assert (await approve(nothing)).status_code == 400  # no photo, no reason
    assert (await approve(with_photo)).status_code == 200
    for c in small[:3]:  # three times a year
        assert (await approve(c)).status_code == 200
    r = await approve(small[3])
    assert r.status_code == 400 and "3 times this year" in r.json()["detail"]
