"""Units of measure (owner, 2026-11-16): preloaded units that can be
benched, and a base, purchase and sales unit per product, so stock stays
exact when a business buys by the sack or carton and sells by the kilo
or the piece."""

from dataclasses import replace


async def units(client) -> dict[str, dict]:
    return {u["code"] or u["name"]: u for u in (await client.get("/units_of_measure")).json()}


async def stock(client, pid):
    return (await client.get(f"/products/{pid}")).json()["on_hand_qty"]


async def sell(client, kernel_auth_header, principal, number, lines):
    r = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json={"org_id": principal.org_id, "payload": {"invoice_number": number, "lines": lines}},
    )
    assert r.status_code == 204, r.text


async def test_the_standard_units_are_preloaded_with_kra_codes(client):
    u = await units(client)
    assert u["kg"]["category"] == "weight" and u["kg"]["etims_code"] == "KG" and u["kg"]["ratio"] == 1
    assert u["g"]["ratio"] == 0.001 and u["g"]["etims_code"] == "GRM"
    assert u["l"]["etims_code"] == "LTR" and u["ml"]["ratio"] == 0.001
    assert u["pc"]["etims_code"] == "U" and u["dozen"]["ratio"] == 12
    assert u["carton"]["ratio"] is None  # a pack: each product sets its size
    # Asking again doesn't add them twice.
    assert len(await units(client)) == len(u)


async def test_benching_a_unit(client, as_principal, principal):
    as_principal(replace(principal, role="admin"))
    u = await units(client)
    r = await client.patch(f"/units_of_measure/{u['yd']['id']}", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    shown = (await client.get("/units_of_measure", params={"include_benched": False})).json()
    assert "yd" not in {x["code"] for x in shown}
    # A unit in use can't be benched.
    await client.post("/products", json={"name": "Sugar", "base_uom_id": u["kg"]["id"]})
    r = await client.patch(f"/units_of_measure/{u['kg']['id']}", json={"active": False})
    assert r.status_code == 409
    # A preloaded unit's size is fixed.
    r = await client.patch(f"/units_of_measure/{u['g']['id']}", json={"ratio": 2})
    assert r.status_code == 422


async def test_a_product_without_units_is_counted_in_pieces(client):
    u = await units(client)
    p = (await client.post("/products", json={"name": "Soap", "on_hand_qty": 5})).json()
    assert p["base_uom_id"] == u["pc"]["id"] == p["sales_uom_id"] == p["purchase_uom_id"]
    assert p["sales_factor"] == 1 and p["purchase_factor"] == 1
    assert p["on_hand_qty"] == 5 and isinstance(p["on_hand_qty"], int)


async def test_units_in_a_category_convert_by_themselves(client):
    u = await units(client)
    # Stocked in kg, sold per 500 g bag priced by weight in grams: the factor
    # comes from the units, whatever the request said.
    p = await client.post(
        "/products",
        json={"name": "Rice", "base_uom_id": u["kg"]["id"], "sales_uom_id": u["g"]["id"], "sales_factor": 5},
    )
    assert p.status_code == 201, p.text
    assert p.json()["sales_factor"] == 0.001 and p.json()["purchase_factor"] == 1


async def test_a_pack_needs_its_size(client):
    u = await units(client)
    r = await client.post("/products", json={"name": "Sugar", "base_uom_id": u["kg"]["id"], "purchase_uom_id": u["sack"]["id"]})
    assert r.status_code == 422 and "sack" in r.json()["detail"]
    r = await client.post(
        "/products", json={"name": "Sugar", "base_uom_id": u["kg"]["id"], "purchase_uom_id": u["sack"]["id"], "purchase_factor": 50}
    )
    assert r.status_code == 201 and r.json()["purchase_factor"] == 50
    # Changing the purchase unit asks again.
    pid = r.json()["id"]
    r = await client.patch(f"/products/{pid}", json={"purchase_uom_id": u["bag"]["id"]})
    assert r.status_code == 422
    r = await client.patch(f"/products/{pid}", json={"purchase_uom_id": u["bag"]["id"], "purchase_factor": 25})
    assert r.status_code == 200 and r.json()["purchase_factor"] == 25
    # Editing something else keeps the size.
    r = await client.patch(f"/products/{pid}", json={"price_cents": 18000})
    assert r.json()["purchase_factor"] == 25


async def test_buying_by_the_sack_and_selling_by_the_kilo(client, kernel_auth_header, principal):
    u = await units(client)
    sugar = (
        await client.post(
            "/products",
            json={
                "name": "Sugar",
                "base_uom_id": u["kg"]["id"],
                "purchase_uom_id": u["sack"]["id"],
                "purchase_factor": 50,
                "sales_uom_id": u["kg"]["id"],
                "cost_cents": 15000,
                "reorder_point": 30,
            },
        )
    ).json()
    # Restock: twice the reorder point is 60 kg, so 2 sacks at 50 x 150.
    po = (await client.post(f"/purchase_orders/from-product/{sugar['id']}")).json()
    line = po["lines"][0]
    assert line["quantity"] == 2 and line["uom_name"] == "sack" and line["uom_factor"] == 50
    assert line["unit_cost_cents"] == 750000
    await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})
    assert await stock(client, sugar["id"]) == 100

    # Half a kilo and a quarter.
    await sell(client, kernel_auth_header, principal, "POS-SUGAR-1", [
        {"product_id": sugar["id"], "quantity": 0.5, "uom_factor": 1},
        {"product_id": sugar["id"], "quantity": 0.25, "uom_factor": 1},
    ])
    assert await stock(client, sugar["id"]) == 99.25
    moves = [m for m in (await client.get("/stock_moves")).json() if m["reference"] == "POS-SUGAR-1"]
    assert moves[0]["qty_delta"] == -0.75


async def test_selling_by_the_crate_takes_the_bottles(client, kernel_auth_header, principal):
    u = await units(client)
    soda = (
        await client.post(
            "/products",
            json={"name": "Soda 300ml", "on_hand_qty": 48, "sales_uom_id": u["crate"]["id"], "sales_factor": 24},
        )
    ).json()
    # The till copies the factor onto the line ...
    await sell(client, kernel_auth_header, principal, "POS-SODA-1", [{"product_id": soda["id"], "quantity": 1, "uom_factor": 24}])
    assert await stock(client, soda["id"]) == 24
    # ... and a line without one (an older till) uses the product's sales unit.
    await sell(client, kernel_auth_header, principal, "POS-SODA-2", [{"product_id": soda["id"], "quantity": 1}])
    assert await stock(client, soda["id"]) == 0
    # A return puts the crate back.
    await sell(client, kernel_auth_header, principal, "RET-SODA-1", [{"product_id": soda["id"], "quantity": -1, "uom_factor": 24}])
    assert await stock(client, soda["id"]) == 24


async def test_a_purchase_order_line_in_another_unit(client):
    u = await units(client)
    flour = (await client.post("/products", json={"name": "Flour", "base_uom_id": u["kg"]["id"]})).json()
    po = await client.post(
        "/purchase_orders",
        json={"lines": [{"product_id": flour["id"], "quantity": 2, "uom_id": u["t"]["id"], "unit_cost_cents": 9000000}]},
    )
    assert po.status_code == 201, po.text
    line = po.json()["lines"][0]
    assert line["uom_factor"] == 1000 and line["total_cost_cents"] == 18000000
    await client.patch(f"/purchase_orders/{po.json()['id']}/status", json={"status": "received"})
    assert await stock(client, flour["id"]) == 2000
    # A pack on a line needs its size.
    r = await client.post("/purchase_orders", json={"lines": [{"product_id": flour["id"], "quantity": 1, "uom_id": u["bale"]["id"]}]})
    assert r.status_code == 422


async def test_stock_adjusts_by_fractions(client):
    u = await units(client)
    p = (await client.post("/products", json={"name": "Milk", "base_uom_id": u["l"]["id"], "on_hand_qty": 10})).json()
    r = await client.post(f"/products/{p['id']}/adjust-stock", json={"delta": -0.25, "reason": "write_off"})
    assert r.status_code == 200 and r.json()["on_hand_qty"] == 9.75


async def test_goods_received_carry_vat_into_the_purchases_schedule(client, as_principal, principal, monkeypatch):
    import csv
    import io

    from app import purchases

    async def no_kernel(org_id):
        return {"vat_registered": True, "default_code": "B", "rates": [{"code": "B", "rate_bp": 1600}, {"code": "A", "rate_bp": 0}]}

    monkeypatch.setattr(purchases, "get_etims_config", no_kernel)
    as_principal(replace(principal, role="admin"))
    sup = (await client.post("/suppliers", json={"name": "Mumias Sugar", "kra_pin": "P051234567X"})).json()
    sugar = (await client.post("/products", json={"name": "Sugar"})).json()
    flour = (await client.post("/products", json={"name": "Flour", "tax_code": "A"})).json()
    po = (
        await client.post(
            "/purchase_orders",
            json={
                "supplier_id": sup["id"],
                "supplier_invoice_no": "MS-1001",
                "lines": [
                    {"product_id": sugar["id"], "quantity": 10, "unit_cost_cents": 50000},
                    {"product_id": flour["id"], "quantity": 5, "unit_cost_cents": 20000},
                ],
            },
        )
    ).json()
    received = (await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})).json()
    vat = {line["tax_code"]: line["vat_cents"] for line in received["lines"]}
    assert vat == {"B": 80000, "A": 0}
    month = received["received_at"][:7]
    rows = list(csv.reader(io.StringIO((await client.get("/purchase_orders/vat-purchases.csv", params={"month": month})).text)))
    assert rows[0][1] == "PIN of Supplier"
    b = [r for r in rows[1:] if r[7] == "B"][0]
    assert b[1] == "P051234567X" and b[4] == "MS-1001" and b[8:10] == ["5000.00", "800.00"] and b[12] == ""


async def test_paying_a_supplier_once_for_what_came_in(client, as_principal, principal, monkeypatch):
    from app import purchases

    async def no_kernel(org_id):
        return {"vat_registered": True, "default_code": "B", "rates": [{"code": "B", "rate_bp": 1600}]}

    sent = []

    async def fake_publish(event_type, org_id, payload):
        sent.append((event_type, payload))

    monkeypatch.setattr(purchases, "get_etims_config", no_kernel)
    monkeypatch.setattr(purchases, "publish_event", fake_publish)
    as_principal(replace(principal, role="admin"))
    sup = (await client.post("/suppliers", json={"name": "Bidco"})).json()
    oil = (await client.post("/products", json={"name": "Oil"})).json()
    po = (await client.post("/purchase_orders", json={"supplier_id": sup["id"], "lines": [{"product_id": oil["id"], "quantity": 4, "unit_cost_cents": 25000}]})).json()

    early = await client.post(f"/purchase_orders/{po['id']}/pay", json={"method": "mpesa"})
    assert early.status_code == 409  # nothing received, nothing owed yet

    await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})
    assert (await client.post(f"/purchase_orders/{po['id']}/pay", json={"method": "barter"})).status_code == 422
    paid = await client.post(f"/purchase_orders/{po['id']}/pay", json={"method": "mpesa", "reference": "SKD8XYZ"})
    assert paid.status_code == 200
    body = paid.json()
    assert body["paid_method"] == "mpesa" and body["paid_reference"] == "SKD8XYZ" and body["paid_at"]
    assert body["total_due_cents"] == 116000
    event = [p for t, p in sent if t == "inventory.purchase.paid"]
    assert event == [{"purchase_order_id": po["id"], "po_number": po["number"], "supplier_name": "Bidco", "amount_cents": 116000, "method": "mpesa", "reference": "SKD8XYZ"}]

    again = await client.post(f"/purchase_orders/{po['id']}/pay", json={"method": "cash"})
    assert again.status_code == 409


async def test_a_business_not_registered_for_vat_claims_no_input_vat(client, as_principal, principal, monkeypatch):
    from app import purchases

    async def not_registered(org_id):
        return {"vat_registered": False, "default_code": "B", "rates": [{"code": "B", "rate_bp": 1600}]}

    monkeypatch.setattr(purchases, "get_etims_config", not_registered)
    as_principal(replace(principal, role="admin"))
    sugar = (await client.post("/products", json={"name": "Sugar"})).json()
    po = (await client.post("/purchase_orders", json={"lines": [{"product_id": sugar["id"], "quantity": 2, "unit_cost_cents": 10000}]})).json()
    received = (await client.patch(f"/purchase_orders/{po['id']}/status", json={"status": "received"})).json()
    assert [line["vat_cents"] for line in received["lines"]] == [0]
    assert received["total_due_cents"] == 20000
