import uuid


async def test_pos_sale_requires_at_least_one_line(client):
    resp = await client.post("/pos/sales", json={"lines": []})
    assert resp.status_code == 422


async def test_pos_sale_becomes_an_already_paid_invoice(client):
    resp = await client.post(
        "/pos/sales",
        json={
            "client_sale_id": "sale-1",
            "lines": [{"description": "Coffee", "quantity": 2, "unit_price_cents": 300}],
            "amount_cents": 600,
            "method": "cash",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "pos"
    assert body["status"] == "paid"
    assert body["total_cents"] == 600
    assert body["balance_cents"] == 0


async def test_pos_sale_stamps_cashier_identity_from_principal(client, principal):
    resp = await client.post(
        "/pos/sales",
        json={"lines": [{"description": "Coffee", "quantity": 1, "unit_price_cents": 300}], "amount_cents": 300},
    )
    body = resp.json()
    assert body["cashier_user_id"] == principal.user_id
    assert body["cashier_email"] == principal.email


async def test_pos_return_stamps_cashier_identity_of_whoever_processed_it(client):
    sale = (
        await client.post(
            "/pos/sales",
            json={"lines": [{"description": "Coffee", "quantity": 1, "unit_price_cents": 300}], "amount_cents": 300},
        )
    ).json()

    refund = (await client.post(f"/pos/sales/{sale['number']}/return")).json()
    assert refund["cashier_user_id"] is not None
    assert refund["cashier_email"] is not None


async def test_pos_sale_tax_reconciles_against_charged_amount(client):
    """Regression test: pos-engine's Cart.total_cents() (what the
    register actually charged) includes tax, but the raw line items
    don't carry a tax line of their own. Before the fix in
    apps/invoicing/app/main.py's record_pos_sale, summing just the line
    items undercounted what was paid and every taxed POS sale showed a
    negative invoice balance despite being fully paid.
    """
    resp = await client.post(
        "/pos/sales",
        json={
            "client_sale_id": "sale-2",
            "lines": [{"description": "Coffee", "quantity": 1, "unit_price_cents": 1000}],
            "amount_cents": 1080,  # 1000 + 8% tax, matching pos-engine's flat dev tax rate
            "method": "card",
        },
    )
    body = resp.json()
    assert body["total_cents"] == 1080
    assert body["paid_cents"] == 1080
    assert body["balance_cents"] == 0
    tax_lines = [l for l in body["lines"] if l["description"] == "Tax"]
    assert len(tax_lines) == 1
    assert tax_lines[0]["total_cents"] == 80


async def test_pos_sale_publishes_pos_sale_recorded_only_for_catalog_lines(client, monkeypatch):
    captured = []

    async def fake_publish_event(event_type, org_id, payload):
        captured.append((event_type, payload))

    # record_pos_sale publishes both invoicing.pos_sale.recorded
    # (publish_pos_sale_recorded) and invoicing.invoice.paid
    # (publish_invoice_paid) -- both now call this one underlying
    # publish_event in app/events.py (main.py no longer imports
    # publish_event directly at all since that refactor), so capture
    # every call and pick out the one this test actually cares about.
    monkeypatch.setattr("app.events.publish_event", fake_publish_event)

    product_id = str(uuid.uuid4())
    await client.post(
        "/pos/sales",
        json={
            "lines": [
                {"description": "Scanned item", "quantity": 1, "unit_price_cents": 500, "product_id": product_id},
                {"description": "Freeform item", "quantity": 1, "unit_price_cents": 200},
            ],
            "amount_cents": 700,
        },
    )

    sale_events = [payload for event_type, payload in captured if event_type == "invoicing.pos_sale.recorded"]
    assert len(sale_events) == 1
    assert sale_events[0]["lines"] == [{"product_id": product_id, "quantity": 1.0, "unit_cost_cents": None}]


async def test_pos_sale_discounted_line_does_not_show_a_false_balance(client):
    """Regression test for the bug this PR's record_pos_sale fix closes:
    before accounting for discount_bp in InvoiceLine.total_cents, a
    discounted line's gross price overstated the invoice total, and
    since the reconciliation only ever added a line for a *positive*
    shortfall, a discount-driven negative adjustment was silently
    dropped -- leaving every discounted POS sale showing a nonzero
    outstanding balance despite being fully paid at the register.
    """
    resp = await client.post(
        "/pos/sales",
        json={
            # $10 line, 10% off -> $9 subtotal, 8% tax -> $9.72 charged
            # (matches pos-engine's discount_and_tax_compose_correctly test)
            "lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 1000, "discount_bp": 1000}],
            "amount_cents": 972,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_cents"] == 972
    assert body["paid_cents"] == 972
    assert body["balance_cents"] == 0

    widget_line = next(l for l in body["lines"] if l["description"] == "Widget")
    assert widget_line["total_cents"] == 900  # discount applied before tax

    tax_lines = [l for l in body["lines"] if l["description"] == "Tax"]
    assert len(tax_lines) == 1
    assert tax_lines[0]["total_cents"] == 72


async def test_pos_sale_persists_discount_bp_and_unit_cost_cents(client):
    product_id = str(uuid.uuid4())
    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [
                {
                    "description": "Widget",
                    "quantity": 1,
                    "unit_price_cents": 1000,
                    "discount_bp": 2000,
                    "unit_cost_cents": 400,
                    "product_id": product_id,
                }
            ],
            "amount_cents": 800,
        },
    )
    body = resp.json()
    line = body["lines"][0]
    assert line["discount_bp"] == 2000
    assert line["unit_cost_cents"] == 400
    assert line["total_cents"] == 800  # 1000 * (1 - 0.20)


async def test_pos_sale_overstated_gross_without_discount_still_reconciles_as_tax(client):
    """Same reconciliation path, zero discount -- confirms the adjustment
    is still labeled "Tax" (not "Discount") when it's positive."""
    resp = await client.post(
        "/pos/sales",
        json={"lines": [{"description": "Widget", "quantity": 1, "unit_price_cents": 1000}], "amount_cents": 1050},
    )
    body = resp.json()
    adjustment_lines = [l for l in body["lines"] if l["description"] in ("Tax", "Discount")]
    assert len(adjustment_lines) == 1
    assert adjustment_lines[0]["description"] == "Tax"
    assert adjustment_lines[0]["total_cents"] == 50
