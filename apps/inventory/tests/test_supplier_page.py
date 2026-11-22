"""The supplier page (plan 12.6): a supplier's session sees and updates
only their own sent purchase orders."""

from friday_common import Principal


def as_supplier(principal, supplier_id):
    return Principal(
        user_id=f"supplier:{supplier_id}",
        org_id=principal.org_id,
        role="supplier",
        email="sales@acme.test",
        via="supplier",
    )


async def _ordered_po(client, supplier_id):
    po = (
        await client.post(
            "/purchase_orders",
            json={"supplier_id": supplier_id, "lines": [{"description": "Sugar 50kg", "quantity": 4, "unit_cost_cents": 500000}]},
        )
    ).json()
    resp = await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "ordered"})
    assert resp.status_code == 200, resp.text
    return po


async def test_a_supplier_sees_and_updates_only_their_sent_orders(client, principal, as_principal):
    acme = (await client.post("/suppliers", json={"name": "Acme", "email": "sales@acme.test"})).json()
    other = (await client.post("/suppliers", json={"name": "Other"})).json()
    mine = await _ordered_po(client, acme["id"])
    theirs = await _ordered_po(client, other["id"])
    draft = (await client.post("/purchase_orders", json={"supplier_id": acme["id"]})).json()

    # Staff can't use the supplier routes.
    assert (await client.get("/supplier/purchase_orders")).status_code == 403

    as_principal(as_supplier(principal, acme["id"]))
    listed = (await client.get("/supplier/purchase_orders")).json()
    assert [p["id"] for p in listed] == [mine["id"]], "only their own, never a draft"
    for po in (theirs, draft):
        r = await client.post(f"/supplier/purchase_orders/{po['id']}/status", json={"status": "acknowledged"})
        assert r.status_code == 404

    r = await client.post(f"/supplier/purchase_orders/{mine['id']}/status", json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["supplier_status"] == "acknowledged"
    r = await client.post(f"/supplier/purchase_orders/{mine['id']}/status", json={"status": "dispatched", "note": "On the 2pm truck"})
    assert r.json()["supplier_status"] == "dispatched" and r.json()["supplier_note"] == "On the 2pm truck"
    r = await client.post(f"/supplier/purchase_orders/{mine['id']}/status", json={"status": "acknowledged"})
    assert r.status_code == 400

    pdf = b"%PDF-1.4 fake"
    bad = await client.put(
        f"/supplier/purchase_orders/{mine['id']}/invoice?number=INV-9&invoice_date=2026-11-22",
        content=b"x",
        headers={"content-type": "text/plain"},
    )
    assert bad.status_code == 415
    r = await client.put(
        f"/supplier/purchase_orders/{mine['id']}/invoice?number=INV-9&invoice_date=2026-11-22",
        content=pdf,
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["supplier_invoice_no"] == "INV-9" and r.json()["invoice_file_sha"]
    assert (await client.get(f"/supplier/purchase_orders/{mine['id']}/invoice")).content == pdf
    # The supplier can't reach the business's own routes.
    assert (await client.get("/purchase_orders")).status_code == 403

    # The business sees the status and opens the file.
    as_principal(principal)
    po = (await client.get(f"/purchase_orders/{mine['id']}")).json()
    assert po["supplier_status"] == "dispatched" and po["supplier_invoice_no"] == "INV-9"
    assert (await client.get(f"/purchase_orders/{mine['id']}/invoice-file")).content == pdf
