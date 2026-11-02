from friday_common.testing import make_principal


async def test_create_opportunity_applies_defaults(client):
    resp = await client.post("/opportunities", json={"contact_name": "Ada Lovelace"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["stage"] == "new"
    assert body["priority"] == "medium"
    assert body["value_cents"] == 0
    assert body["next_step_at"] is None


async def test_create_opportunity_rejects_invalid_stage(client):
    resp = await client.post("/opportunities", json={"contact_name": "Ada", "stage": "bogus"})
    assert resp.status_code == 422


async def test_create_opportunity_rejects_invalid_priority(client):
    resp = await client.post("/opportunities", json={"contact_name": "Ada", "priority": "bogus"})
    assert resp.status_code == 422


async def test_update_rejects_invalid_stage(client):
    created = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()
    resp = await client.patch(f"/opportunities/{created['id']}", json={"stage": "bogus"})
    assert resp.status_code == 422


async def test_winning_an_opportunity_publishes_crm_opportunity_won(client, monkeypatch):
    """The one cross-app integration point in the MVP -- see
    ARCHITECTURE.md's "Cross-app integration" section. Invoicing drafts
    an invoice off exactly this event payload shape
    (apps/invoicing/app/webhooks.py), so a shape regression here breaks
    that silently.
    """
    captured = {}

    async def fake_publish_event(event_type, org_id, payload):
        captured["type"] = event_type
        captured["org_id"] = org_id
        captured["payload"] = payload

    monkeypatch.setattr("app.main.publish_event", fake_publish_event)

    created = (
        await client.post(
            "/opportunities",
            json={
                "contact_name": "Ada Lovelace",
                "contact_email": "ada@example.com",
                "company": "Analytical Engines Inc",
                "value_cents": 50000,
                "currency": "USD",
            },
        )
    ).json()

    resp = await client.patch(f"/opportunities/{created['id']}", json={"stage": "won"})
    assert resp.status_code == 200

    assert captured["type"] == "crm.opportunity.won"
    assert captured["payload"] == {
        "opportunity_id": created["id"],
        "contact_name": "Ada Lovelace",
        "contact_email": "ada@example.com",
        "company": "Analytical Engines Inc",
        "value_cents": 50000,
        "currency": "USD",
    }


async def test_marking_lost_stores_reason_and_does_not_publish_won(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.publish_event", lambda *a, **kw: calls.append(a))

    created = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()
    resp = await client.patch(
        f"/opportunities/{created['id']}", json={"stage": "lost", "lost_reason": "chose a competitor"}
    )
    assert resp.status_code == 200
    assert resp.json()["lost_reason"] == "chose a competitor"
    assert calls == []


async def test_winning_notifies_slack_when_connected(client, monkeypatch):
    async def noop_publish(*a, **kw):
        return None

    monkeypatch.setattr("app.main.publish_event", noop_publish)

    async def fake_config(org_id, provider):
        assert provider == "slack"
        return {"webhook_url": "https://hooks.slack.com/services/fake"}

    notified = {}

    class FakeSlack:
        def __init__(self, config):
            self.config = config

        async def notify(self, text):
            notified["text"] = text

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.SlackProvider", FakeSlack)

    created = (
        await client.post("/opportunities", json={"contact_name": "Ada", "company": "Acme", "value_cents": 1000})
    ).json()
    await client.patch(f"/opportunities/{created['id']}", json={"stage": "won"})

    assert "Won" in notified["text"]
    assert "Acme" in notified["text"]


async def test_winning_skips_slack_when_not_connected(client, monkeypatch):
    async def noop_publish(*a, **kw):
        return None

    monkeypatch.setattr("app.main.publish_event", noop_publish)

    async def fake_config(org_id, provider):
        return {}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)

    created = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()
    # Would raise (SlackProvider.__init__ requires config["webhook_url"]) if
    # the empty-config guard in _notify_slack were ever removed.
    resp = await client.patch(f"/opportunities/{created['id']}", json={"stage": "won"})
    assert resp.status_code == 200


async def test_moving_between_non_won_stages_does_not_publish(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.publish_event", lambda *a, **kw: calls.append(a))

    created = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()
    await client.patch(f"/opportunities/{created['id']}", json={"stage": "qualified"})
    await client.patch(f"/opportunities/{created['id']}", json={"stage": "proposition"})

    assert calls == []


async def test_org_isolation_hides_records_from_other_orgs(client, as_principal, principal):
    created = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()

    as_principal(make_principal())  # a different org entirely

    assert (await client.get(f"/opportunities/{created['id']}")).status_code == 404
    assert (await client.get("/opportunities")).json() == []

    as_principal(principal)
    assert (await client.get(f"/opportunities/{created['id']}")).status_code == 200


async def test_next_step_at_roundtrips(client):
    created = (
        await client.post(
            "/opportunities", json={"contact_name": "Ada", "next_step_at": "2026-12-01T00:00:00Z"}
        )
    ).json()
    assert created["next_step_at"].startswith("2026-12-01")

    cleared = (
        await client.patch(f"/opportunities/{created['id']}", json={"next_step_at": None})
    ).json()
    assert cleared["next_step_at"] is None
