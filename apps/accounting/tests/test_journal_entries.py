async def _account_id(client, code: str) -> str:
    accounts = (await client.get("/accounts")).json()
    return next(a["id"] for a in accounts if a["code"] == code)


async def test_balanced_journal_entry_is_created(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")

    resp = await client.post(
        "/journal_entries",
        json={
            "entry_date": "2026-01-15",
            "memo": "Cash sale",
            "lines": [
                {"account_id": cash, "debit_cents": 1000},
                {"account_id": revenue, "credit_cents": 1000},
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["total_debit_cents"] == 1000
    assert body["total_credit_cents"] == 1000
    assert len(body["lines"]) == 2


async def test_unbalanced_journal_entry_is_rejected(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")

    resp = await client.post(
        "/journal_entries",
        json={
            "entry_date": "2026-01-15",
            "lines": [
                {"account_id": cash, "debit_cents": 1000},
                {"account_id": revenue, "credit_cents": 900},
            ],
        },
    )
    assert resp.status_code == 422


async def test_zero_amount_journal_entry_is_rejected(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")

    resp = await client.post(
        "/journal_entries",
        json={
            "entry_date": "2026-01-15",
            "lines": [
                {"account_id": cash, "debit_cents": 0},
                {"account_id": revenue, "credit_cents": 0},
            ],
        },
    )
    assert resp.status_code == 422


async def test_journal_entry_requires_at_least_two_lines(client):
    cash = await _account_id(client, "1010")
    resp = await client.post(
        "/journal_entries",
        json={"entry_date": "2026-01-15", "lines": [{"account_id": cash, "debit_cents": 1000}]},
    )
    assert resp.status_code == 422


async def test_posting_a_draft_entry(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    entry = (
        await client.post(
            "/journal_entries",
            json={
                "entry_date": "2026-01-15",
                "lines": [
                    {"account_id": cash, "debit_cents": 500},
                    {"account_id": revenue, "credit_cents": 500},
                ],
            },
        )
    ).json()

    resp = await client.patch(f"/journal_entries/{entry['id']}/status", json={"status": "posted"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"


async def test_posted_entry_cannot_revert_to_draft(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    entry = (
        await client.post(
            "/journal_entries",
            json={
                "entry_date": "2026-01-15",
                "lines": [
                    {"account_id": cash, "debit_cents": 500},
                    {"account_id": revenue, "credit_cents": 500},
                ],
            },
        )
    ).json()
    await client.patch(f"/journal_entries/{entry['id']}/status", json={"status": "posted"})

    resp = await client.patch(f"/journal_entries/{entry['id']}/status", json={"status": "draft"})
    assert resp.status_code == 400


async def test_invalid_status_rejected(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    entry = (
        await client.post(
            "/journal_entries",
            json={
                "entry_date": "2026-01-15",
                "lines": [
                    {"account_id": cash, "debit_cents": 500},
                    {"account_id": revenue, "credit_cents": 500},
                ],
            },
        )
    ).json()

    resp = await client.patch(f"/journal_entries/{entry['id']}/status", json={"status": "bogus"})
    assert resp.status_code == 422


async def test_list_and_get_journal_entry(client):
    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    created = (
        await client.post(
            "/journal_entries",
            json={
                "entry_date": "2026-01-15",
                "lines": [
                    {"account_id": cash, "debit_cents": 500},
                    {"account_id": revenue, "credit_cents": 500},
                ],
            },
        )
    ).json()

    assert (await client.get("/journal_entries")).json()[0]["id"] == created["id"]
    assert (await client.get(f"/journal_entries/{created['id']}")).status_code == 200


async def test_org_isolation_on_journal_entries(client, as_principal, principal):
    from friday_common.testing import make_principal

    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    created = (
        await client.post(
            "/journal_entries",
            json={
                "entry_date": "2026-01-15",
                "lines": [
                    {"account_id": cash, "debit_cents": 500},
                    {"account_id": revenue, "credit_cents": 500},
                ],
            },
        )
    ).json()

    as_principal(make_principal())
    assert (await client.get(f"/journal_entries/{created['id']}")).status_code == 404
    assert (await client.get("/journal_entries")).json() == []
