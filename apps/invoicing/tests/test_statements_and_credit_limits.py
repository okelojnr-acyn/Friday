"""Roadmap item 5: customers can be edited, credit sales stop at a
customer's credit limit, statements carry a balance, and a sent invoice
schedules its overdue reminders."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import main as main_mod
from app.statements import statement_rows


@pytest.fixture
def events(monkeypatch):
    captured = []

    async def fake_publish_event(event_type, org_id, payload, **kw):
        captured.append((event_type, payload, kw.get("deliver_at")))

    async def no_vat(org_id):
        return {"vat_registered": False}

    monkeypatch.setattr("app.events.publish_event", fake_publish_event)
    monkeypatch.setattr("app.statements.publish_event", fake_publish_event)
    monkeypatch.setattr(main_mod, "get_etims_config", no_vat)
    return captured


def credit(name, cents):
    return {
        "client_sale_id": f"guss:{uuid.uuid4()}",
        "channel": "guss",
        "currency": "KES",
        "amount_cents": cents,
        "on_credit": True,
        "customer_name": name,
        "lines": [{"description": "Rice", "quantity": 1, "unit_price_cents": cents}],
    }


def test_statement_carries_the_balance_in_and_runs_it():
    d = lambda n: datetime(2026, 11, n, tzinfo=UTC)  # noqa: E731
    inv = lambda n, day, total, pays: SimpleNamespace(  # noqa: E731
        number=n, issued_at=d(day), grand_total_cents=total,
        payments=[SimpleNamespace(received_at=d(pd), amount_cents=pc) for pd, pc in pays],
    )
    out = statement_rows([inv("A", 1, 10_000, [(3, 4_000)]), inv("B", 10, 5_000, [(12, 5_000)])], d(5), d(30))
    assert out["opening_cents"] == 6_000
    assert [(r["number"], r["amount_cents"], r["balance_cents"]) for r in out["rows"]] == [("B", 5_000, 11_000), ("B", -5_000, 6_000)]
    assert out["closing_cents"] == 6_000


async def test_a_customer_can_be_edited_and_given_a_credit_limit(client, events):
    c = (await client.post("/customers", json={"name": "Mary Wanjiru"})).json()
    r = await client.patch(f"/customers/{c['id']}", json={"credit_limit_cents": 150_000, "company": "Mama Mboga"})
    assert r.status_code == 200 and r.json()["credit_limit_cents"] == 150_000 and r.json()["company"] == "Mama Mboga"
    assert (await client.get(f"/customers/{c['id']}")).json()["name"] == "Mary Wanjiru"

    assert (await client.post("/pos/sales", json=credit("Mary Wanjiru", 100_000))).status_code == 201
    over = await client.post("/pos/sales", json=credit("mary wanjiru", 60_000))
    assert over.status_code == 409 and "credit limit" in over.json()["detail"]

    # 0 (what a blank form field sends) is no limit, as before.
    await client.patch(f"/customers/{c['id']}", json={"credit_limit_cents": 0})
    assert (await client.post("/pos/sales", json=credit("Mary Wanjiru", 60_000))).status_code == 201

    st = (await client.get(f"/customers/{c['id']}/statement")).json()
    assert st["closing_cents"] == 160_000 and len(st["rows"]) == 2


async def test_sending_an_invoice_schedules_reminders_after_it_falls_due(client, events, monkeypatch):
    async def no_pay_request(*_a, **_k):
        return ""

    monkeypatch.setattr(main_mod.pay_requests, "start", no_pay_request)
    c = (await client.post("/customers", json={"name": "Otieno", "payment_terms_days": 7})).json()
    inv = (await client.post("/invoices", json={"customer_id": c["id"], "currency": "KES", "lines": [{"description": "Work", "quantity": 1, "unit_price_cents": 50_000}]})).json()
    assert (await client.patch(f"/invoices/{inv['id']}/status", json={"status": "sent"})).status_code == 200
    reminders = [(p["nth"], at) for t, p, at in events if t == "invoicing.invoice.remind"]
    assert [n for n, _ in reminders] == [1, 2, 3]
    assert all(at > datetime.now(UTC) + timedelta(days=7) for _, at in reminders)
