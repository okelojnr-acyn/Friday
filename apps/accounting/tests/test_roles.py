"""Plan section 12, step 2 in Accounting: the books are for owners and
admins (and viewers with the accounting job); Guss's drafts may come from
the staff who record expenses."""

from dataclasses import replace


def entry(source="manual"):
    return {
        "entry_date": "2026-11-22",
        "memo": "Fuel",
        "source": source,
        "lines": [{"account_id": None, "debit_cents": 100}, {"account_id": None, "credit_cents": 100}],
    }


async def test_who_reads_and_writes_the_books(client, as_principal, principal):
    accounts = (await client.get("/accounts")).json()
    cash = next(a for a in accounts if a["code"] == "1010")["id"]
    other = next(a for a in accounts if a["code"] != "1010")["id"]
    body = entry()
    body["lines"][0]["account_id"], body["lines"][1]["account_id"] = other, cash

    staff = replace(principal, role="member", perms=("cashier",))
    as_principal(staff)
    assert (await client.get("/accounts")).status_code == 200  # the chart, for Guss to book with
    assert (await client.get("/journal_entries")).status_code == 403
    assert (await client.post("/journal_entries", json=body)).status_code == 403
    guss = dict(body, source="guss", source_ref="guss:1")
    assert (await client.post("/journal_entries", json=guss)).status_code == 201  # a draft from Guss

    viewer = replace(principal, role="viewer")
    as_principal(viewer)
    assert (await client.get("/journal_entries")).status_code == 403
    auditor = replace(principal, role="viewer", perms=("accounting",))
    as_principal(auditor)
    assert (await client.get("/journal_entries")).status_code == 200

    branch = replace(principal, role="branch_manager", locs=("loc-west",))
    as_principal(branch)
    pnl = await client.get("/reports/profit-and-loss", params={"start_date": "2026-11-01", "end_date": "2026-11-30"})
    assert pnl.status_code == 403  # whole business
