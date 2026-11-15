"""Importing products and suppliers (plan 2.4): idempotent on the source's
id, only mapped columns written, per-row errors, admins only."""

from dataclasses import replace

from friday_common.testing import make_principal


def batch(rows, source="old-shop"):
    return {"source": source, "rows": rows}


async def test_import_is_idempotent_and_updates_only_mapped_columns(client, as_principal, principal):
    admin = replace(principal, role="admin")
    as_principal(admin)
    first = await client.post(
        "/import/product",
        json=batch(
            [
                {"external_id": "P-1", "values": {"name": "Sugar 1kg", "sku": "SUG1", "price_cents": "KSh 1,250.50"}},
                {"external_id": "P-2", "values": {"name": "Salt", "sku": "SAL", "price_cents": "45"}},
            ]
        ),
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"inserted": 2, "updated": 0, "errors": []}

    products = {p["sku"]: p for p in (await client.get("/products")).json()}
    assert products["SUG1"]["price_cents"] == 125050
    assert products["SAL"]["price_cents"] == 4500

    # Someone sets a reorder point in Friday; a re-import that doesn't map
    # it must leave it alone, and must not duplicate the products.
    sugar = products["SUG1"]
    await client.patch(f"/products/{sugar['id']}", json={"reorder_point": 7})
    again = await client.post(
        "/import/product",
        json=batch([{"external_id": "P-1", "values": {"name": "Sugar 1kg (new)", "price_cents": "1300"}}]),
    )
    assert again.json() == {"inserted": 0, "updated": 1, "errors": []}
    products = {p["sku"]: p for p in (await client.get("/products")).json()}
    assert len(products) == 2
    assert products["SUG1"]["name"] == "Sugar 1kg (new)"
    assert products["SUG1"]["price_cents"] == 130000
    assert products["SUG1"]["reorder_point"] == 7

    # The same id from another source is another product.
    other = await client.post("/import/product", json=batch([{"external_id": "P-1", "values": {"name": "X"}}], "csv"))
    assert other.json()["inserted"] == 1


async def test_bad_rows_are_reported_and_the_rest_imported(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    resp = await client.post(
        "/import/supplier",
        json=batch(
            [
                {"external_id": "S-1", "values": {"name": "Bidco", "email": "orders@bidco.example"}},
                {"external_id": "S-2", "values": {"name": "", "email": "x@y.example"}},
                {"external_id": "S-3", "values": {"name": "Kapa", "email": "not an email"}},
                {"external_id": "S-1", "values": {"name": "Bidco again"}},
            ]
        ),
    )
    body = resp.json()
    assert body["inserted"] == 1
    assert sorted(e["external_id"] for e in body["errors"]) == ["S-1", "S-2", "S-3"]


async def test_unknown_fields_and_unmapped_required_fields_are_refused(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    r = await client.post("/import/product", json=batch([{"external_id": "1", "values": {"name": "A", "on_hand_qty": 5}}]))
    assert r.status_code == 400
    r = await client.post("/import/product", json=batch([{"external_id": "1", "values": {"sku": "A"}}]))
    assert r.status_code == 400 and "Name" in r.json()["detail"]
    assert (await client.post("/import/nothing", json=batch([]))).status_code == 404


async def test_members_and_assistants_cannot_import(client, as_principal, principal):
    rows = batch([{"external_id": "1", "values": {"name": "A"}}])
    as_principal(principal)  # a member
    assert (await client.post("/import/product", json=rows)).status_code == 403
    as_principal(replace(principal, role="owner", via="guss"))
    assert (await client.post("/import/product", json=rows)).status_code == 403


async def test_imports_stay_inside_the_org(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    await client.post("/import/supplier", json=batch([{"external_id": "S-1", "values": {"name": "Ours"}}]))
    as_principal(make_principal(role="admin"))
    r = await client.post("/import/supplier", json=batch([{"external_id": "S-1", "values": {"name": "Theirs"}}]))
    assert r.json()["inserted"] == 1
    names = [s["name"] for s in (await client.get("/suppliers")).json()]
    assert names == ["Theirs"]


async def test_targets_describe_the_fields(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    targets = {t["entity"]: t for t in (await client.get("/import/targets")).json()}
    assert set(targets) == {"product", "supplier"}
    assert {"name": "price_cents", "label": "Price", "kind": "cents", "required": False} in targets["product"]["fields"]
