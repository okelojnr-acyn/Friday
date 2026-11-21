"""Selling on credit, paying debts, and partial returns (Guss follow-ups,
2026-11-21). Money reaches the books only when it actually comes in."""

import uuid

import pytest

from app import main as main_mod


@pytest.fixture
def events(monkeypatch):
    captured = []

    async def fake_publish_event(event_type, org_id, payload):
        captured.append((event_type, payload))

    async def no_vat(org_id):
        return {"vat_registered": False}

    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    monkeypatch.setattr(main_mod, "get_etims_config", no_vat)
    return captured


def sale(qty=3, price=10000, **kw):
    body = {
        "client_sale_id": f"guss:{uuid.uuid4()}",
        "channel": "guss",
        "currency": "KES",
        "method": "cash",
        "amount_cents": qty * price,
        "lines": [{"description": "Rice", "quantity": qty, "unit_price_cents": price}],
    }
    body.update(kw)
    return body


def credit(name, qty=1, price=100000):
    return sale(qty=qty, price=price, on_credit=True, customer_name=name)


def kinds(events):
    return [t for t, _ in events]


async def test_a_credit_sale_moves_stock_but_not_money(client, events):
    made = await client.post("/pos/sales", json=credit("John Kamau"))
    assert made.status_code == 201, made.text
    sale_ = made.json()
    assert sale_["status"] == "sent" and sale_["customer_id"]
    assert kinds(events) == ["invoicing.pos_sale.recorded"]  # stock, no books yet

    # Same customer whatever the case or spacing.
    again = (await client.post("/pos/sales", json=credit("  john   kamau "))).json()
    assert again["customer_id"] == sale_["customer_id"]
    owes = (await client.get("/pos/debts", params={"customer": "JOHN KAMAU"})).json()
    assert len(owes) == 1 and owes[0]["owed_cents"] == 200000 and len(owes[0]["sales"]) == 2

    assert (await client.post("/pos/sales", json=sale(on_credit=True))).status_code == 422  # no name


async def test_paying_a_debt_settles_the_oldest_first_once(client, events):
    first = (await client.post("/pos/sales", json=credit("Mary"))).json()
    second = (await client.post("/pos/sales", json=credit("Mary"))).json()
    events.clear()
    pay = {"customer_name": "mary", "amount_cents": 150000, "method": "mpesa", "client_payment_id": "guss:p1"}
    done = await client.post("/pos/debts/payments", json=pay)
    assert done.status_code == 201, done.text
    assert done.json()["settled"] == [first["number"]] and done.json()["owed_cents"] == 50000
    # Only the settled sale reaches the books, at its full amount, as M-Pesa.
    paid = [p for t, p in events if t == "invoicing.invoice.paid"]
    assert len(paid) == 1 and paid[0]["payments"] == [{"method": "mpesa", "amount_cents": 100000}]

    # Sent again (Guss retries): recorded once.
    again = (await client.post("/pos/debts/payments", json=pay)).json()
    assert again["already_recorded"] and again["owed_cents"] == 50000

    too_much = {**pay, "client_payment_id": "guss:p2", "amount_cents": 60000}
    refused = await client.post("/pos/debts/payments", json=too_much)
    assert refused.status_code == 422 and "50000" in refused.json()["detail"]

    rest = await client.post("/pos/debts/payments", json={**pay, "client_payment_id": "guss:p3", "amount_cents": 50000})
    assert rest.json()["settled"] == [second["number"]] and rest.json()["owed_cents"] == 0
    assert (await client.get("/pos/debts", params={"customer": "Mary"})).json() == []
    unknown = {**pay, "client_payment_id": "guss:p4", "customer_name": "Nobody"}
    assert (await client.post("/pos/debts/payments", json=unknown)).status_code == 404


async def test_taking_back_an_unpaid_credit_sale_cancels_it_without_a_refund(client, events):
    made = (await client.post("/pos/sales", json=credit("Otieno", qty=2))).json()
    events.clear()
    back = await client.post(f"/pos/sales/{made['number']}/return", json={})
    assert back.status_code == 201, back.text
    assert back.json()["status"] == "void"
    assert kinds(events) == ["invoicing.pos_sale.recorded"]  # restock only: no money went out
    assert (await client.get("/pos/debts", params={"customer": "Otieno"})).json() == []

    # Part-paid: can't be cancelled from here.
    other = (await client.post("/pos/sales", json=credit("Wanjiru"))).json()
    pay = {"customer_name": "Wanjiru", "amount_cents": 1000, "method": "cash", "client_payment_id": "guss:w1"}
    await client.post("/pos/debts/payments", json=pay)
    assert (await client.post(f"/pos/sales/{other['number']}/return", json={})).status_code == 409


async def test_part_of_a_sale_can_come_back(client, events):
    made = (await client.post("/pos/sales", json=sale(qty=3, price=10000))).json()
    line_id = made["lines"][0]["id"]
    events.clear()
    one = await client.post(f"/pos/sales/{made['number']}/return", json={"lines": [{"line_id": line_id, "quantity": 1}]})
    assert one.status_code == 201, one.text
    assert one.json()["lines"][0]["quantity"] == -1
    paid = [p for t, p in events if t == "invoicing.invoice.paid"][0]
    assert paid["paid_amount_cents"] == -10000
    # The sale stands for the two kept.
    assert (await client.get(f"/pos/sales/{made['number']}")).json()["status"] == "paid"

    too_many = {"lines": [{"line_id": line_id, "quantity": 3}]}
    assert (await client.post(f"/pos/sales/{made['number']}/return", json=too_many)).status_code == 422
    rest = await client.post(f"/pos/sales/{made['number']}/return", json={})
    assert rest.json()["lines"][0]["quantity"] == -2
    assert (await client.get(f"/pos/sales/{made['number']}")).json()["status"] == "void"
    assert (await client.post(f"/pos/sales/{made['number']}/return", json={})).status_code == 400
