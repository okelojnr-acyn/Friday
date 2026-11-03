import uuid


async def _account_id(client, code: str) -> str:
    accounts = (await client.get("/accounts")).json()
    return next(a["id"] for a in accounts if a["code"] == code)


async def _post_entry(client, entry_date: str, lines: list[dict], post: bool = True) -> dict:
    created = (await client.post("/journal_entries", json={"entry_date": entry_date, "lines": lines})).json()
    if post:
        await client.patch(f"/journal_entries/{created['id']}/status", json={"status": "posted"})
    return created


async def test_profit_and_loss_splits_income_and_expense(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    cogs = await _account_id(client, "5000")

    await _post_entry(
        client,
        "2026-02-10",
        [{"account_id": cash, "debit_cents": 10000}, {"account_id": revenue, "credit_cents": 10000}],
    )
    await _post_entry(
        client,
        "2026-02-11",
        [{"account_id": cogs, "debit_cents": 4000}, {"account_id": cash, "credit_cents": 4000}],
    )
    # Outside the query range -- must not be counted.
    await _post_entry(
        client,
        "2026-03-01",
        [{"account_id": cash, "debit_cents": 999}, {"account_id": revenue, "credit_cents": 999}],
    )

    resp = await client.get("/reports/profit-and-loss", params={"start_date": "2026-02-01", "end_date": "2026-02-28"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_income_cents"] == 10000
    assert body["total_expenses_cents"] == 4000
    assert body["net_income_cents"] == 6000
    assert [l["code"] for l in body["income"]] == ["4000"]
    assert [l["code"] for l in body["expenses"]] == ["5000"]


async def test_profit_and_loss_ignores_draft_entries(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    await _post_entry(
        client,
        "2026-02-10",
        [{"account_id": cash, "debit_cents": 5000}, {"account_id": revenue, "credit_cents": 5000}],
        post=False,
    )

    resp = await client.get("/reports/profit-and-loss", params={"start_date": "2026-02-01", "end_date": "2026-02-28"})
    body = resp.json()
    assert body["total_income_cents"] == 0
    assert body["income"] == []


async def test_balance_sheet_balances(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    equity = await _account_id(client, "3000")

    await _post_entry(
        client,
        "2026-01-05",
        [{"account_id": cash, "debit_cents": 50000}, {"account_id": equity, "credit_cents": 50000}],
    )
    await _post_entry(
        client,
        "2026-01-10",
        [{"account_id": cash, "debit_cents": 2000}, {"account_id": revenue, "credit_cents": 2000}],
    )

    resp = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_assets_cents"] == 52000
    assert body["net_income_to_date_cents"] == 2000
    # Equity accounts (50000) + net income folded in (2000) = assets, since
    # every journal entry already balances by construction.
    assert body["total_equity_cents"] == 52000
    assert body["total_assets_cents"] == body["total_liabilities_cents"] + body["total_equity_cents"]


async def test_cash_flow_groups_by_source_and_computes_balances(client, kernel_auth_header, principal):
    cash = await _account_id(client, "1010")
    equity = await _account_id(client, "3000")

    # Opening balance, before the query window.
    await _post_entry(
        client,
        "2026-01-01",
        [{"account_id": cash, "debit_cents": 10000}, {"account_id": equity, "credit_cents": 10000}],
    )

    # A manual entry inside the window.
    await _post_entry(
        client,
        "2026-02-05",
        [{"account_id": equity, "debit_cents": 1000}, {"account_id": cash, "credit_cents": 1000}],
    )
    # An invoicing-sourced entry inside the window, via the real webhook.
    await client.post(
        "/internal/webhooks/invoice-paid",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_id": str(uuid.uuid4()),
                "invoice_number": "INV-CF-1",
                "subtotal_cents": 3000,
                "tax_cents": 0,
                "paid_amount_cents": 3000,
            },
        },
    )

    # The invoice-paid webhook always posts with today's real date, so the
    # window has to stretch far enough into the future to catch it
    # regardless of when this test actually runs -- while still starting
    # after the opening-balance entry above.
    resp = await client.get("/reports/cash-flow", params={"start_date": "2026-01-02", "end_date": "2099-12-31"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["beginning_balance_cents"] == 10000
    by_source = {l["source"]: l["net_cents"] for l in body["by_source"]}
    assert by_source == {"manual": -1000, "invoicing": 3000}
    assert body["net_change_cents"] == 2000
    assert body["ending_balance_cents"] == 12000


async def test_account_ledger_running_balance_in_date_order(client):
    cash = await _account_id(client, "1010")
    equity = await _account_id(client, "3000")

    await _post_entry(
        client,
        "2026-01-10",
        [{"account_id": cash, "debit_cents": 1000}, {"account_id": equity, "credit_cents": 1000}],
    )
    await _post_entry(
        client,
        "2026-01-05",
        [{"account_id": cash, "debit_cents": 500}, {"account_id": equity, "credit_cents": 500}],
    )

    resp = await client.get(f"/accounts/{cash}/ledger")
    assert resp.status_code == 200
    lines = resp.json()
    assert [l["entry_date"] for l in lines] == ["2026-01-05", "2026-01-10"]
    assert [l["balance_cents"] for l in lines] == [500, 1500]


async def test_account_ledger_unknown_account_404s(client):
    resp = await client.get(f"/accounts/{uuid.uuid4()}/ledger")
    assert resp.status_code == 404
