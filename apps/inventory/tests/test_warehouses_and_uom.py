from friday_common.testing import make_principal


async def test_create_warehouse(client):
    resp = await client.post("/warehouses", json={"name": "Main", "code": "MAIN", "is_default": True})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Main"
    assert body["is_default"] is True


async def test_org_isolation_on_warehouses(client, as_principal, principal):
    await client.post("/warehouses", json={"name": "Main"})
    as_principal(make_principal())
    assert (await client.get("/warehouses")).json() == []


async def test_create_unit_of_measure(client):
    resp = await client.post("/units_of_measure", json={"name": "Box of 12", "abbreviation": "bx12"})
    assert resp.status_code == 201
    assert resp.json()["abbreviation"] == "bx12"


async def test_product_defaults_to_standard_valuation_and_unit_conversion(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()
    assert product["valuation_method"] == "standard"
    assert float(product["uom_conversion_factor"]) == 1.0
    assert product["default_warehouse_id"] is None
    assert product["uom_id"] is None


async def test_product_rejects_unknown_valuation_method(client):
    resp = await client.post("/products", json={"name": "Widget", "price_cents": 999, "valuation_method": "bogus"})
    assert resp.status_code == 422


async def test_product_can_be_created_with_warehouse_and_uom(client):
    warehouse = (await client.post("/warehouses", json={"name": "Main"})).json()
    uom = (await client.post("/units_of_measure", json={"name": "Box of 12"})).json()

    resp = await client.post(
        "/products",
        json={
            "name": "Widget",
            "price_cents": 999,
            "default_warehouse_id": warehouse["id"],
            "uom_id": uom["id"],
            "uom_conversion_factor": "12",
            "valuation_method": "fifo",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["default_warehouse_id"] == warehouse["id"]
    assert body["uom_id"] == uom["id"]
    assert float(body["uom_conversion_factor"]) == 12.0
    assert body["valuation_method"] == "fifo"


async def test_update_product_rejects_unknown_valuation_method(client):
    product = (await client.post("/products", json={"name": "Widget", "price_cents": 999})).json()
    resp = await client.patch(f"/products/{product['id']}", json={"valuation_method": "bogus"})
    assert resp.status_code == 422


async def test_initial_stock_move_inherits_product_default_warehouse(client):
    warehouse = (await client.post("/warehouses", json={"name": "Main"})).json()
    product = (
        await client.post(
            "/products",
            json={"name": "Widget", "price_cents": 999, "on_hand_qty": 5, "default_warehouse_id": warehouse["id"]},
        )
    ).json()

    moves = (await client.get("/stock_moves")).json()
    assert moves[0]["warehouse_id"] == warehouse["id"]


async def test_adjust_stock_inherits_default_warehouse_unless_overridden(client):
    warehouse_a = (await client.post("/warehouses", json={"name": "A"})).json()
    warehouse_b = (await client.post("/warehouses", json={"name": "B"})).json()
    product = (
        await client.post(
            "/products", json={"name": "Widget", "price_cents": 999, "default_warehouse_id": warehouse_a["id"]}
        )
    ).json()

    await client.post(f"/products/{product['id']}/adjust-stock", json={"delta": 5})
    await client.post(
        f"/products/{product['id']}/adjust-stock", json={"delta": -2, "warehouse_id": warehouse_b["id"]}
    )

    moves = (await client.get("/stock_moves")).json()
    by_delta = {m["qty_delta"]: m["warehouse_id"] for m in moves}
    assert by_delta[5] == warehouse_a["id"]
    assert by_delta[-2] == warehouse_b["id"]
