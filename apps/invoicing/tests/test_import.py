"""Importing customers (plan 2.4); the shared behaviour is tested in
apps/inventory/tests/test_import.py."""

from dataclasses import replace


async def test_customers_import_and_reimport(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    rows = [{"external_id": "C-9", "values": {"name": "Mama Mboga", "email": "MAMA@Example.com", "payment_terms_days": "14"}}]
    first = await client.post("/import/customer", json={"source": "old-crm", "rows": rows})
    assert first.json() == {"inserted": 1, "updated": 0, "errors": []}
    again = await client.post("/import/customer", json={"source": "old-crm", "rows": rows})
    assert again.json() == {"inserted": 0, "updated": 1, "errors": []}
    customers = (await client.get("/customers")).json()
    assert len(customers) == 1
    assert customers[0]["email"] == "mama@example.com"
    assert customers[0]["payment_terms_days"] == 14
