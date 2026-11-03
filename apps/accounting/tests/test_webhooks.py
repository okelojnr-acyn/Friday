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
