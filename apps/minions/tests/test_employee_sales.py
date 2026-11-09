"""invoicing.pos_sale.recorded -- the event this app subscribes to (see
kernel/internal/gateway/events.go) to attribute a POS sale to whichever
employee rang it up. Mirrors apps/inventory/tests/test_webhooks.py's
pattern for the same event, just for a different subscriber.
"""


def _event(org_id: str, invoice_number: str, cashier_user_id: str | None, cashier_email: str | None, cents: int):
    return {
        "org_id": org_id,
        "payload": {
            "invoice_number": invoice_number,
            "amount_cents": cents,
            "cashier_user_id": cashier_user_id,
            "cashier_email": cashier_email,
            "lines": [],
        },
    }


async def test_pos_sale_recorded_attributes_sale_by_cashier_user_id(client, kernel_auth_header, principal):
    await client.post("/employees", json={"name": "Alex", "email": principal.email})
    # Backfills Employee.user_id = principal.user_id via
    # _resolve_my_employee's claim-by-email logic (same self-service path
    # /me/wallet always uses) -- so the webhook's lookup below hits the
    # user_id fast path directly, not the email fallback.
    await client.put("/me/wallet", json={"wallet_address": "0xabc", "wallet_network": "ethereum"})

    resp = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json=_event(principal.org_id, "POS-20261109-ABC123", principal.user_id, principal.email, 1000),
    )
    assert resp.status_code == 204

    sales = (await client.get("/employee_sales")).json()
    assert len(sales) == 1
    assert sales[0]["invoice_number"] == "POS-20261109-ABC123"
    assert sales[0]["amount_cents"] == 1000


async def test_pos_sale_recorded_falls_back_to_email_and_claims_user_id(client, kernel_auth_header, principal):
    employee = (
        await client.post("/employees", json={"name": "Jess", "email": "jess@example.com"})
    ).json()
    assert employee["user_id"] == ""

    resp = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json=_event(principal.org_id, "POS-1", "some-other-user-id", "jess@example.com", 500),
    )
    assert resp.status_code == 204

    sales = (await client.get("/employee_sales")).json()
    assert sales[0]["employee_id"] == employee["id"]
    assert sales[0]["employee_name"] == "Jess"


async def test_pos_sale_recorded_skipped_when_cashier_is_not_a_provisioned_employee(client, kernel_auth_header, principal):
    resp = await client.post(
        "/internal/webhooks/pos-sale",
        headers=kernel_auth_header,
        json=_event(principal.org_id, "POS-2", principal.user_id, "nobody@example.com", 500),
    )
    assert resp.status_code == 204
    assert (await client.get("/employee_sales")).json() == []


async def test_pos_sale_recorded_is_idempotent_on_replay(client, kernel_auth_header, principal):
    await client.post("/employees", json={"name": "Alex", "email": principal.email})
    event = _event(principal.org_id, "POS-3", principal.user_id, principal.email, 500)

    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=event)
    await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header, json=event)

    sales = (await client.get("/employee_sales")).json()
    assert len(sales) == 1


async def test_pos_sale_recorded_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/pos-sale",
        json=_event(principal.org_id, "POS-4", principal.user_id, principal.email, 500),
    )
    assert resp.status_code == 401
