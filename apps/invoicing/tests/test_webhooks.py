import uuid


async def test_crm_won_webhook_creates_customer_and_draft_invoice(client, kernel_auth_header, principal):
    opportunity_id = str(uuid.uuid4())
    resp = await client.post(
        "/internal/webhooks/crm-won",
        headers=kernel_auth_header,
        json={
            "org_id": principal.org_id,
            "payload": {
                "opportunity_id": opportunity_id,
                "contact_name": "Ada Lovelace",
                "contact_email": "ada@example.com",
                "company": "Analytical Engines Inc",
                "value_cents": 75000,
                "currency": "USD",
            },
        },
    )
    assert resp.status_code == 201

    invoices = (await client.get("/invoices")).json()
    assert len(invoices) == 1
    assert invoices[0]["source"] == "crm"
    assert invoices[0]["source_ref"] == opportunity_id
    assert invoices[0]["status"] == "draft"
    assert invoices[0]["total_cents"] == 75000

    customers = (await client.get("/customers")).json()
    assert len(customers) == 1
    assert customers[0]["email"] == "ada@example.com"


async def test_crm_won_webhook_reuses_existing_customer_by_email(client, kernel_auth_header, principal):
    async def fire(opportunity_id: str):
        await client.post(
            "/internal/webhooks/crm-won",
            headers=kernel_auth_header,
            json={
                "org_id": principal.org_id,
                "payload": {
                    "opportunity_id": opportunity_id,
                    "contact_name": "Ada Lovelace",
                    "contact_email": "ada@example.com",
                    "value_cents": 1000,
                },
            },
        )

    await fire(str(uuid.uuid4()))
    await fire(str(uuid.uuid4()))

    customers = (await client.get("/customers")).json()
    assert len(customers) == 1

    invoices = (await client.get("/invoices")).json()
    assert len(invoices) == 2
    assert all(inv["customer_id"] == customers[0]["id"] for inv in invoices)


async def test_crm_won_webhook_requires_kernel_token(client, principal):
    resp = await client.post(
        "/internal/webhooks/crm-won",
        json={"org_id": principal.org_id, "payload": {"contact_name": "Ada"}},
    )
    assert resp.status_code == 401
