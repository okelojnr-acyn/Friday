"""Spending plan part D: a spend charged to a customer is offered on their
next invoice and, once added, never again; what was spent on each project
(approved and paid claims) is there for its budget."""

from friday_common.testing import make_principal


async def test_billable_spends_and_spent_on_projects(client, as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    await client.post("/employees", json={"name": "Jane", "email": principal.email})
    as_principal(principal)
    send = lambda **kw: client.post("/expense_claims", json={"description": "Cable", "amount_cents": 30_000, **kw})  # noqa: E731
    assert (await send(billable=True)).status_code == 422  # which customer?
    billed = (await send(billable=True, customer_id="cust-1", customer_name="Acme", for_kind="project", for_id="p-1", for_label="Acme fit-out")).json()
    other = (await send(for_kind="project", for_id="p-1", for_label="Acme fit-out", amount_cents=20_000)).json()
    waiting = (await send(for_kind="project", for_id="p-1", for_label="Acme fit-out", amount_cents=99_000)).json()
    assert (billed["billable"], billed["customer_name"]) == (True, "Acme")

    as_principal(admin)
    for c in (billed, other):
        await client.patch(f"/expense_claims/{c['id']}/status", json={"status": "approved"})
    assert [c["id"] for c in (await client.get("/spends/billable?customer_id=cust-1")).json()] == [billed["id"]]
    r = await client.post("/spends/billed", json={"invoice_id": "inv-1", "claim_ids": [billed["id"]]})
    assert r.status_code == 200 and r.json()[0]["billed_invoice_id"] == "inv-1"
    assert (await client.post("/spends/billed", json={"invoice_id": "inv-2", "claim_ids": [billed["id"]]})).status_code == 409
    assert (await client.post("/spends/billed", json={"invoice_id": "inv-2", "claim_ids": [other["id"]]})).status_code == 409  # not billable
    assert (await client.get("/spends/billable?customer_id=cust-1")).json() == []

    spent = (await client.get("/spends/spent?for_kind=project")).json()
    assert spent == [{"for_id": "p-1", "currency": billed["currency"], "spent_cents": 50_000}]  # the waiting one isn't spent yet
    assert waiting["status"] == "submitted"
