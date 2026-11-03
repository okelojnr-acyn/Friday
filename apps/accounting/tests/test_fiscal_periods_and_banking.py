async def test_create_fiscal_period(client):
    resp = await client.post(
        "/fiscal_periods",
        json={"name": "FY2026-Q1", "start_date": "2026-01-01", "end_date": "2026-03-31"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "open"


async def test_create_fiscal_period_rejects_unknown_status(client):
    resp = await client.post(
        "/fiscal_periods",
        json={
            "name": "FY2026-Q1",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "status": "bogus",
        },
    )
    assert resp.status_code == 422


async def test_create_bank_account_and_transaction_then_match(client):
    accounts = (await client.get("/accounts")).json()
    cash = next(a["id"] for a in accounts if a["code"] == "1010")

    bank_account = (
        await client.post("/bank_accounts", json={"name": "Main Checking", "account_id": cash})
    ).json()
    assert bank_account["currency"] == "USD"

    txn = (
        await client.post(
            "/bank_transactions",
            json={
                "bank_account_id": bank_account["id"],
                "txn_date": "2026-01-10",
                "description": "Deposit",
                "amount_cents": 5000,
            },
        )
    ).json()
    assert txn["status"] == "unmatched"

    matched = await client.patch(f"/bank_transactions/{txn['id']}/match")
    assert matched.status_code == 200
    assert matched.json()["status"] == "matched"
