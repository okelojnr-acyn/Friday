"""HR plan phase 2: the month's PAYE, NSSF and SHIF returns from payslips."""

import csv
import io

from friday_common.testing import make_principal


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


async def test_the_months_returns_from_the_payslips(client, as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    bad = await client.post("/employees", json={"name": "X", "email": "x@x.test", "kra_pin": "123"})
    assert bad.status_code == 422  # not a KRA PIN
    jane = (
        await client.post(
            "/employees",
            json={"name": "Jane", "email": "jane@example.com", "pay_rate_cents": 10_000_000, "kra_pin": "a012345678z",
                  "national_id": "12345678", "nssf_number": "NS-77", "sha_number": "SHA9"},
        )
    ).json()
    assert jane["kra_pin"] == "A012345678Z"
    tom = (await client.post("/employees", json={"name": "Tom", "email": "tom@example.com", "pay_rate_cents": 5_000_000})).json()
    # Lines with nowhere to pay are blocked and never filed; both can be paid.
    for email in ("jane@example.com", "tom@example.com"):
        as_principal(make_principal(org_id=principal.org_id, email=email))
        await client.put("/me/wallet", json={"wallet_address": "0xabc", "wallet_network": "base"})
    as_principal(admin)
    run = (
        await client.post(
            "/payroll_runs",
            json={"period_start": "2026-03-01T00:00:00Z", "period_end": "2026-03-28T00:00:00Z", "currency": "KES",
                  "employee_ids": [jane["id"], tom["id"]]},
        )
    ).json()
    # A draft run isn't filed; an approved one is.
    assert len(_rows((await client.get("/payroll_runs/returns.csv?kind=paye&month=2026-03")).text)) == 0
    await client.post(f"/payroll_runs/{run['id']}/approve")

    paye = {r["Employee"]: r for r in _rows((await client.get("/payroll_runs/returns.csv?kind=paye&month=2026-03")).text)}
    j = paye["Jane"]
    assert (j["KRA PIN"], j["Gross pay"], j["Taxable pay"], j["PAYE"]) == ("A012345678Z", "100000.00", "89750.00", "19308.35")
    assert (j["Tax charged"], j["Personal relief"], j["Housing Levy (employer)"]) == ("21708.35", "2400.00", "1500.00")
    assert paye["Tom"]["Note"] == "no KRA PIN"  # filled in before filing

    nssf = {r["Employee"]: r for r in _rows((await client.get("/payroll_runs/returns.csv?kind=nssf&month=2026-03")).text)}
    assert (nssf["Jane"]["Tier I (employee)"], nssf["Jane"]["Tier II (employee)"], nssf["Jane"]["Total"]) == ("540.00", "5460.00", "12000.00")
    shif = {r["Employee"]: r for r in _rows((await client.get("/payroll_runs/returns.csv?kind=shif&month=2026-03")).text)}
    assert (shif["Jane"]["SHA number"], shif["Jane"]["SHIF"]) == ("SHA9", "2750.00")
    assert shif["Tom"]["Note"] == "no ID, SHA number"

    # Another month has nothing; only whoever handles everyone's pay may file.
    assert len(_rows((await client.get("/payroll_runs/returns.csv?kind=paye&month=2026-04")).text)) == 0
    as_principal(make_principal(org_id=principal.org_id, role="branch_manager"))
    assert (await client.get("/payroll_runs/returns.csv?kind=paye&month=2026-03")).status_code == 403
    # Staff don't see others' numbers in the staff list.
    as_principal(make_principal(org_id=principal.org_id, role="team_leader", team=()))
    for row in (await client.get("/employees")).json():
        assert row["kra_pin"] == "" or row["email"] == "test@example.com"
