import uuid


async def _journal_entries(client):
    return (await client.get("/journal_entries")).json()


async def _account_id(client, code: str) -> str:
    accounts = (await client.get("/accounts")).json()
    return next(a["id"] for a in accounts if a["code"] == code)


async def test_invoice_paid_posts_cash_revenue_and_tax(client, kernel_auth_header, principal):
    invoice_id = str(uuid.uuid4())
    resp = await client.post(
        "/internal/webhooks/invoice-paid",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_id": invoice_id,
                "invoice_number": "INV-0001",
                "subtotal_cents": 10000,
                "tax_cents": 800,
                "paid_amount_cents": 10800,
                "lines": [],
            },
        },
    )
    assert resp.status_code == 204

    entries = await _journal_entries(client)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source"] == "invoicing"
    assert entry["source_ref"] == invoice_id
    assert entry["status"] == "posted"
    assert entry["total_debit_cents"] == 10800
    assert entry["total_credit_cents"] == 10800

    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    tax_payable = await _account_id(client, "2200")
    by_account = {line["account_id"]: line for line in entry["lines"]}
    assert by_account[cash]["debit_cents"] == 10800
    assert by_account[revenue]["credit_cents"] == 10000
    assert by_account[tax_payable]["credit_cents"] == 800


async def test_invoice_paid_mirrors_sides_for_a_refund(client, kernel_auth_header, principal):
    """A POS return or credit note publishes a negative amount -- the
    ledger itself must never carry a negative entry."""
    invoice_id = str(uuid.uuid4())
    resp = await client.post(
        "/internal/webhooks/invoice-paid",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_id": invoice_id,
                "invoice_number": "RET-0001",
                "subtotal_cents": -5000,
                "tax_cents": -400,
                "paid_amount_cents": -5400,
                "lines": [],
            },
        },
    )
    assert resp.status_code == 204

    entries = await _journal_entries(client)
    entry = entries[0]
    assert entry["total_debit_cents"] == 5400
    assert entry["total_credit_cents"] == 5400

    cash = await _account_id(client, "1010")
    revenue = await _account_id(client, "4000")
    tax_payable = await _account_id(client, "2200")
    by_account = {line["account_id"]: line for line in entry["lines"]}
    assert by_account[cash]["credit_cents"] == 5400
    assert by_account[revenue]["debit_cents"] == 5000
    assert by_account[tax_payable]["debit_cents"] == 400


async def test_invoice_paid_is_idempotent_on_replay(client, kernel_auth_header, principal):
    invoice_id = str(uuid.uuid4())
    body = {
        "org_id": principal.org_id,
        "payload": {
            "invoice_id": invoice_id,
            "invoice_number": "INV-0002",
            "subtotal_cents": 2000,
            "tax_cents": 0,
            "paid_amount_cents": 2000,
            "lines": [],
        },
    }
    for _ in range(2):
        resp = await client.post("/internal/webhooks/invoice-paid", headers=kernel_auth_header, json=body)
        assert resp.status_code == 204

    assert len(await _journal_entries(client)) == 1


async def test_invoice_paid_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/invoice-paid",
        json={"org_id": principal.org_id, "payload": {"invoice_id": str(uuid.uuid4())}},
    )
    assert resp.status_code == 401


async def test_pos_sale_cogs_posts_for_lines_with_a_known_cost(client, kernel_auth_header, principal):
    resp = await client.post(
        "/internal/webhooks/pos-sale-cogs",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_number": "POS-0001",
                "lines": [
                    {"product_id": str(uuid.uuid4()), "quantity": 3, "unit_cost_cents": 200},
                    {"product_id": str(uuid.uuid4()), "quantity": 1, "unit_cost_cents": None},
                ],
            },
        },
    )
    assert resp.status_code == 204

    entries = await _journal_entries(client)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source"] == "pos"
    assert entry["source_ref"] == "POS-0001"
    assert entry["total_debit_cents"] == 600
    assert entry["total_credit_cents"] == 600

    cogs = await _account_id(client, "5000")
    inventory_asset = await _account_id(client, "1400")
    by_account = {line["account_id"]: line for line in entry["lines"]}
    assert by_account[cogs]["debit_cents"] == 600
    assert by_account[inventory_asset]["credit_cents"] == 600


async def test_pos_sale_cogs_skips_lines_with_no_cost(client, kernel_auth_header, principal):
    """Freeform/ad-hoc POS lines (or any line rung up before POS threaded
    cost through) carry no unit_cost_cents -- a documented gap, not a bug:
    there's no cost to post against, so no entry is created at all."""
    resp = await client.post(
        "/internal/webhooks/pos-sale-cogs",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {"invoice_number": "POS-0002", "lines": [{"quantity": 1, "unit_cost_cents": None}]},
        },
    )
    assert resp.status_code == 204
    assert await _journal_entries(client) == []


async def test_pos_sale_cogs_reverses_for_a_return(client, kernel_auth_header, principal):
    """return_pos_sale republishes the same event shape with negated
    quantities -- the COGS entry should reverse (Cr COGS / Dr Inventory)
    rather than post a negative amount."""
    resp = await client.post(
        "/internal/webhooks/pos-sale-cogs",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_number": "RET-0002",
                "lines": [{"product_id": str(uuid.uuid4()), "quantity": -2, "unit_cost_cents": 150}],
            },
        },
    )
    assert resp.status_code == 204

    entries = await _journal_entries(client)
    entry = entries[0]
    assert entry["total_debit_cents"] == 300
    assert entry["total_credit_cents"] == 300

    cogs = await _account_id(client, "5000")
    inventory_asset = await _account_id(client, "1400")
    by_account = {line["account_id"]: line for line in entry["lines"]}
    assert by_account[cogs]["credit_cents"] == 300
    assert by_account[inventory_asset]["debit_cents"] == 300


async def test_pos_sale_cogs_is_idempotent_on_replay(client, kernel_auth_header, principal):
    body = {
        "org_id": principal.org_id,
        "payload": {
            "invoice_number": "POS-0003",
            "lines": [{"product_id": str(uuid.uuid4()), "quantity": 1, "unit_cost_cents": 500}],
        },
    }
    for _ in range(2):
        resp = await client.post("/internal/webhooks/pos-sale-cogs", headers=kernel_auth_header, json=body)
        assert resp.status_code == 204

    assert len(await _journal_entries(client)) == 1


async def test_pos_sale_cogs_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/pos-sale-cogs",
        json={"org_id": principal.org_id, "payload": {"lines": []}},
    )
    assert resp.status_code == 401


async def test_payroll_paid_posts_salary_expense_and_cash(client, kernel_auth_header, principal):
    payroll_run_id = str(uuid.uuid4())
    resp = await client.post(
        "/internal/webhooks/payroll-paid",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {"payroll_run_id": payroll_run_id, "amount_cents": 250000, "currency": "USD"},
        },
    )
    assert resp.status_code == 204

    entries = await _journal_entries(client)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source"] == "payroll"
    assert entry["source_ref"] == payroll_run_id
    assert entry["status"] == "posted"
    assert entry["total_debit_cents"] == 250000
    assert entry["total_credit_cents"] == 250000

    salary_expense = await _account_id(client, "6000")
    cash = await _account_id(client, "1010")
    by_account = {line["account_id"]: line for line in entry["lines"]}
    assert by_account[salary_expense]["debit_cents"] == 250000
    assert by_account[cash]["credit_cents"] == 250000


async def test_payroll_paid_is_idempotent_on_replay(client, kernel_auth_header, principal):
    body = {
        "org_id": principal.org_id,
        "payload": {"payroll_run_id": str(uuid.uuid4()), "amount_cents": 1000, "currency": "USD"},
    }
    for _ in range(2):
        resp = await client.post("/internal/webhooks/payroll-paid", headers=kernel_auth_header, json=body)
        assert resp.status_code == 204

    assert len(await _journal_entries(client)) == 1


async def test_payroll_paid_skips_zero_amount(client, kernel_auth_header, principal):
    """Every line in the run blocked/failed -- nothing was actually paid,
    so there's nothing to post."""
    resp = await client.post(
        "/internal/webhooks/payroll-paid",
        headers=kernel_auth_header,
        json={"org_id": principal.org_id, "payload": {"payroll_run_id": str(uuid.uuid4()), "amount_cents": 0}},
    )
    assert resp.status_code == 204
    assert await _journal_entries(client) == []


async def test_payroll_paid_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/payroll-paid",
        json={"org_id": principal.org_id, "payload": {"payroll_run_id": str(uuid.uuid4()), "amount_cents": 1000}},
    )
    assert resp.status_code == 401


async def test_a_till_sale_books_revenue_without_its_vat_and_money_where_it_went(client, kernel_auth_header, principal):
    # 1,160 with 16% VAT inside (160): 700 cash, 460 M-Pesa.
    resp = await client.post(
        "/internal/webhooks/invoice-paid",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "invoice_id": str(uuid.uuid4()),
                "invoice_number": "POS-VAT-1",
                "subtotal_cents": 116000,
                "tax_cents": 0,
                "vat_cents": 16000,
                "payments": [{"method": "cash", "amount_cents": 70000}, {"method": "mpesa", "amount_cents": 46000}],
                "lines": [],
            },
        },
    )
    assert resp.status_code == 204
    entry = (await _journal_entries(client))[0]
    assert entry["total_debit_cents"] == entry["total_credit_cents"] == 116000
    by = {line["account_id"]: line for line in entry["lines"]}
    assert by[await _account_id(client, "1010")]["debit_cents"] == 70000
    assert by[await _account_id(client, "1020")]["debit_cents"] == 46000
    assert by[await _account_id(client, "4000")]["credit_cents"] == 100000
    assert by[await _account_id(client, "2200")]["credit_cents"] == 16000


async def test_goods_received_book_stock_input_vat_and_what_is_owed(client, kernel_auth_header, principal):
    po_id = str(uuid.uuid4())
    body = {
        "org_id": principal.org_id,
        "payload": {"purchase_order_id": po_id, "po_number": "PO-1", "supplier_name": "Mumias", "supplier_invoice_no": "INV-77", "net_cents": 500000, "vat_cents": 80000},
    }
    assert (await client.post("/internal/webhooks/purchase-received", headers=kernel_auth_header, json=body)).status_code == 204
    entries = await _journal_entries(client)
    assert len(entries) == 1 and entries[0]["source"] == "inventory"
    by = {line["account_id"]: line for line in entries[0]["lines"]}
    assert by[await _account_id(client, "1400")]["debit_cents"] == 500000
    assert by[await _account_id(client, "1500")]["debit_cents"] == 80000
    assert by[await _account_id(client, "2000")]["credit_cents"] == 580000
    # Delivered twice, booked once.
    body["id"] = str(uuid.uuid4())
    await client.post("/internal/webhooks/purchase-received", headers=kernel_auth_header, json=body)
    assert len(await _journal_entries(client)) == 1


async def _post_paid(client, kernel_auth_header, principal, **payload):
    payload.setdefault("invoice_id", str(uuid.uuid4()))
    payload.setdefault("invoice_number", "T-1")
    payload.setdefault("lines", [])
    resp = await client.post(
        "/internal/webhooks/invoice-paid",
        headers=kernel_auth_header,
        json={"org_id": principal.org_id, "payload": payload},
    )
    assert resp.status_code == 204
    entry = (await _journal_entries(client))[0]
    assert entry["total_debit_cents"] == entry["total_credit_cents"]
    by = {}
    for line in entry["lines"]:
        acc = next(a["code"] for a in (await client.get("/accounts")).json() if a["id"] == line["account_id"])
        by[acc] = (line["debit_cents"], line["credit_cents"])
    return by


async def test_a_till_sale_with_a_rounding_line_and_card_balances(client, kernel_auth_header, principal):
    # Lines 990.10 incl. 136.57 VAT plus a -0.10 rounding line; 500 cash, 490 card.
    by = await _post_paid(
        client, kernel_auth_header, principal,
        subtotal_cents=99000, tax_cents=0, vat_cents=13657,
        payments=[{"method": "cash", "amount_cents": 50000}, {"method": "card", "amount_cents": 49000}],
    )
    assert by["1010"] == (50000, 0)
    assert by["1030"] == (49000, 0)
    assert by["4000"] == (0, 99000 - 13657)
    assert by["2200"] == (0, 13657)


async def test_payments_that_do_not_add_up_are_booked_as_cash(client, kernel_auth_header, principal):
    by = await _post_paid(
        client, kernel_auth_header, principal,
        subtotal_cents=10000, tax_cents=0, vat_cents=0,
        payments=[{"method": "mpesa", "amount_cents": 4000}],
    )
    assert by["1010"] == (10000, 0)
    assert "1020" not in by


async def test_a_till_refund_reverses_revenue_vat_and_cash(client, kernel_auth_header, principal):
    by = await _post_paid(
        client, kernel_auth_header, principal,
        subtotal_cents=-11600, tax_cents=0, vat_cents=-1600,
        payments=[{"method": "refund", "amount_cents": -11600}],
    )
    assert by["4000"] == (10000, 0)
    assert by["2200"] == (1600, 0)
    assert by["1010"] == (0, 11600)


async def test_a_credit_note_on_a_typed_invoice_reverses_its_vat(client, kernel_auth_header, principal):
    # Typed invoice: prices before tax, 16% on top; credited in full.
    by = await _post_paid(
        client, kernel_auth_header, principal,
        subtotal_cents=-10000, tax_cents=-1600, vat_cents=-1600,
        payments=[{"method": "refund", "amount_cents": -11600}],
    )
    assert by["4000"] == (10000, 0)
    assert by["2200"] == (1600, 0)
    assert by["1010"] == (0, 11600)


async def test_an_invoice_paid_by_bank_in_two_parts_lands_in_the_bank(client, kernel_auth_header, principal):
    by = await _post_paid(
        client, kernel_auth_header, principal,
        subtotal_cents=10000, tax_cents=1600, vat_cents=1600,
        payments=[{"method": "bank_transfer", "amount_cents": 6000}, {"method": "bank_transfer", "amount_cents": 5600}],
    )
    assert by["1030"] == (11600, 0)
    assert by["4000"] == (0, 10000)
    assert by["2200"] == (0, 1600)


async def test_paying_a_supplier_clears_what_is_owed_from_the_right_account(client, kernel_auth_header, principal):
    po_id = str(uuid.uuid4())
    received = {"org_id": principal.org_id, "payload": {"purchase_order_id": po_id, "po_number": "PO-2", "supplier_name": "Bidco", "net_cents": 100000, "vat_cents": 16000}}
    await client.post("/internal/webhooks/purchase-received", headers=kernel_auth_header, json=received)
    paid = {"org_id": principal.org_id, "payload": {"purchase_order_id": po_id, "po_number": "PO-2", "supplier_name": "Bidco", "amount_cents": 116000, "method": "mpesa", "reference": "SKD8XYZ"}}
    assert (await client.post("/internal/webhooks/purchase-paid", headers=kernel_auth_header, json=paid)).status_code == 204
    paid["id"] = str(uuid.uuid4())
    await client.post("/internal/webhooks/purchase-paid", headers=kernel_auth_header, json=paid)
    entries = await _journal_entries(client)
    assert len(entries) == 2
    pay = next(e for e in entries if e["source_ref"] == "paid:" + po_id)
    by = {line["account_id"]: line for line in pay["lines"]}
    assert by[await _account_id(client, "2000")]["debit_cents"] == 116000
    assert by[await _account_id(client, "1020")]["credit_cents"] == 116000
    assert "SKD8XYZ" in pay["memo"]


async def test_purchase_paid_requires_kernel_token(client, principal):
    resp = await client.post("/internal/webhooks/purchase-paid", json={"org_id": principal.org_id, "payload": {}})
    assert resp.status_code == 401


async def test_a_reversed_payment_and_a_repayment_are_separate_postings(client, kernel_auth_header, principal):
    """A credit sale paid, the payment reversed, then paid again: three
    postings for one invoice, each once, netting to one sale."""
    invoice_id = str(uuid.uuid4())

    async def paid(amount, posting_ref=None):
        payload = {
            "invoice_id": invoice_id,
            "invoice_number": "POS-CREDIT",
            "subtotal_cents": amount,
            "tax_cents": 0,
            "paid_amount_cents": amount,
            "payments": [{"method": "mpesa", "amount_cents": amount}],
            "lines": [],
        }
        if posting_ref:
            payload["posting_ref"] = posting_ref
        r = await client.post(
            "/internal/webhooks/invoice-paid",
            headers=kernel_auth_header,
            json={"org_id": principal.org_id, "payload": payload},
        )
        assert r.status_code == 204

    await paid(5000)
    await paid(-5000, f"{invoice_id}:reversed:p1")
    await paid(-5000, f"{invoice_id}:reversed:p1")  # delivered again: once
    await paid(5000)  # the invoice itself again: still once
    await paid(5000, f"{invoice_id}:p2")
    refs = sorted(e["source_ref"] for e in await _journal_entries(client) if e["source_ref"].startswith(invoice_id))
    assert refs == sorted([invoice_id, f"{invoice_id}:reversed:p1", f"{invoice_id}:p2"])
    mpesa = await _account_id(client, "1020")
    revenue = await _account_id(client, "4000")
    lines = [l for e in await _journal_entries(client) if e["source_ref"].startswith(invoice_id) for l in e["lines"]]
    net = lambda acct: sum(l["debit_cents"] - l["credit_cents"] for l in lines if l["account_id"] == acct)  # noqa: E731
    assert net(mpesa) == 5000 and net(revenue) == -5000
