async def test_list_accounts_lazily_seeds_default_chart_of_accounts(client):
    resp = await client.get("/accounts")
    assert resp.status_code == 200
    codes = {a["code"] for a in resp.json()}
    assert codes == {"1010", "1200", "1400", "2200", "3000", "4000", "5000", "6000"}


async def test_listing_accounts_twice_does_not_duplicate_defaults(client):
    await client.get("/accounts")
    resp = await client.get("/accounts")
    codes = [a["code"] for a in resp.json()]
    assert len(codes) == len(set(codes))


async def test_create_account_rejects_unknown_type(client):
    resp = await client.post("/accounts", json={"code": "9999", "name": "Bogus", "type": "nonsense"})
    assert resp.status_code == 422


async def test_create_account(client):
    resp = await client.post("/accounts", json={"code": "7000", "name": "Marketing Expense", "type": "expense"})
    assert resp.status_code == 201
    assert resp.json()["code"] == "7000"


async def test_org_isolation_on_accounts(client, as_principal, principal):
    """Each org lazily gets its own default Chart of Accounts -- GET
    /accounts for a second org must never return the first org's rows,
    even though both orgs end up with the same set of codes."""
    from friday_common.testing import make_principal

    first_org_accounts = (await client.get("/accounts")).json()
    first_org_ids = {a["id"] for a in first_org_accounts}

    as_principal(make_principal())
    second_org_accounts = (await client.get("/accounts")).json()
    second_org_ids = {a["id"] for a in second_org_accounts}

    assert {a["code"] for a in second_org_accounts} == {a["code"] for a in first_org_accounts}
    assert first_org_ids.isdisjoint(second_org_ids)
