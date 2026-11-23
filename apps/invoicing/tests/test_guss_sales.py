"""Guss (the shop assistant) records its sales through the same sales
system as the tills (owner, 2026-11-21), so stock, VAT, the books, eTIMS
and the VAT return all come from one record, and each side sees the
other's sales."""

import uuid

from app import main as main_mod

CFG = {"vat_registered": True, "default_code": "B", "rates": [{"code": "A", "rate_bp": 0}, {"code": "B", "rate_bp": 1600}]}


def guss_sale(**kw):
    body = {
        "client_sale_id": f"guss:{uuid.uuid4()}",
        "channel": "guss",
        "currency": "KES",
        "method": "mpesa",
        "amount_cents": 121000,
        # Shelf prices, VAT inside; Guss doesn't work VAT out itself.
        "lines": [
            {"description": "Cooking oil 1L", "quantity": 2, "unit_price_cents": 58000, "tax_code": "B"},
            {"description": "Maize flour 2kg", "quantity": 1, "unit_price_cents": 5000, "tax_code": "A"},
        ],
    }
    body.update(kw)
    return body


async def test_a_guss_sale_gets_its_vat_here_and_reaches_accounting_like_a_till_sale(client, monkeypatch):
    async def cfg(org_id):
        return CFG

    captured = []

    async def fake_publish_event(event_type, org_id, payload, **_):
        captured.append((event_type, payload))

    monkeypatch.setattr(main_mod, "get_etims_config", cfg)
    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    made = await client.post("/pos/sales", json=guss_sale())
    assert made.status_code == 201, made.text
    paid = [p for t, p in captured if t == "invoicing.invoice.paid"][0]
    assert paid["vat_cents"] == 16000  # 1,160 with 16% inside
    assert paid["vat_by_code"] == {"B": 16000, "A": 0}
    assert paid["payments"] == [{"method": "mpesa", "amount_cents": 121000}]
    assert [t for t, _ in captured].count("invoicing.pos_sale.recorded") == 1  # stock moves once, through Inventory

    # Sent twice (Guss retries), recorded once.
    again = await client.post("/pos/sales", json=guss_sale(client_sale_id=made.json()["source_ref"]))
    assert again.json()["id"] == made.json()["id"]


async def test_a_guss_sale_never_counts_in_a_tills_cash(client, a_till, monkeypatch):
    async def cfg(org_id):
        return CFG

    monkeypatch.setattr(main_mod, "get_etims_config", cfg)
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()
    await client.post("/pos/sales", json={"lines": [{"description": "Bread", "quantity": 1, "unit_price_cents": 1000}], "amount_cents": 1000, "method": "cash"})
    await client.post("/pos/sales", json=guss_sale(method="cash"))
    closed = (await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 1000})).json()
    assert closed["expected_cents"] == 1000


async def test_a_days_sales_list_shows_till_and_guss_sales(client, monkeypatch):
    async def cfg(org_id):
        return CFG

    monkeypatch.setattr(main_mod, "get_etims_config", cfg)
    till = (await client.post("/pos/sales", json={"lines": [{"description": "Bread", "quantity": 1, "unit_price_cents": 1000}], "amount_cents": 1000, "method": "cash"})).json()
    guss = (await client.post("/pos/sales", json=guss_sale())).json()
    day = till["created_at"][:10]
    rows = (await client.get("/pos/sales", params={"day": day})).json()
    assert {(r["number"], r["channel"]) for r in rows} >= {(till["number"], "till"), (guss["number"], "guss")}
    only = (await client.get("/pos/sales", params={"day": day, "channel": "guss"})).json()
    assert [r["number"] for r in only] == [guss["number"]]
    assert only[0]["total_cents"] == 121000 and only[0]["lines"][0]["description"] == "Cooking oil 1L"
    assert sum(line["total_cents"] for line in only[0]["lines"]) == 121000


async def test_a_business_not_registered_for_vat_books_no_vat_on_guss_sales(client, monkeypatch):
    async def cfg(org_id):
        return {**CFG, "vat_registered": False}

    captured = []

    async def fake_publish_event(event_type, org_id, payload, **_):
        captured.append((event_type, payload))

    monkeypatch.setattr(main_mod, "get_etims_config", cfg)
    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    await client.post("/pos/sales", json=guss_sale())
    paid = [p for t, p in captured if t == "invoicing.invoice.paid"][0]
    assert paid["vat_cents"] == 0
