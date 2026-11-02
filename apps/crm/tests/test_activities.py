import uuid

from friday_common.testing import make_principal


async def test_create_activity_requires_existing_opportunity(client):
    resp = await client.post("/activities", json={"opportunity_id": str(uuid.uuid4()), "body": "called them"})
    assert resp.status_code == 404


async def test_activity_create_and_list_roundtrip(client):
    opp = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()

    created = (
        await client.post("/activities", json={"opportunity_id": opp["id"], "body": "Sent proposal"})
    ).json()
    assert created["opportunity_id"] == opp["id"]
    assert created["body"] == "Sent proposal"

    listed = (await client.get("/activities")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


async def test_activities_are_org_isolated(client, as_principal, principal):
    opp = (await client.post("/opportunities", json={"contact_name": "Ada"})).json()
    await client.post("/activities", json={"opportunity_id": opp["id"], "body": "note"})

    as_principal(make_principal())  # a different org entirely
    assert (await client.get("/activities")).json() == []

    as_principal(principal)
    assert len((await client.get("/activities")).json()) == 1
