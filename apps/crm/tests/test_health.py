"""/health must run a real query (2026-11-10: /healthz said ok while every
query failed). Tested via crm only because CI runs pytest per app; the
endpoint itself lives in friday_common.create_app and every app gets it."""


async def test_health_runs_a_real_query(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"


async def test_healthz_is_liveness_only(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
