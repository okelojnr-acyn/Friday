"""Products carry their eTIMS tax type and are registered with KRA
(/saveItem) only when automation is on (a fake KRA here)."""

import json
from dataclasses import replace

import httpx
import pytest

from app import etims as etims_module

CFG = {"enabled": True, "environment": "sandbox", "branch_id": "00", "cmc_key": "k", "tax_pin": "P051234567X", "default_code": "B"}


@pytest.fixture(autouse=True)
def kernel_settings(monkeypatch):
    async def fake(org_id):
        return CFG

    monkeypatch.setattr(etims_module, "get_etims_config", fake)


async def test_tax_type_on_a_product(client):
    r = await client.post("/products", json={"name": "Bread", "price_cents": 6500, "tax_code": "E", "etims_item_class": "5022110801"})
    assert r.status_code == 201, r.text
    assert r.json()["tax_code"] == "E" and r.json()["etims_packaging_unit"] == "NT"
    bad = await client.post("/products", json={"name": "X", "tax_code": "Z"})
    assert bad.status_code == 422


async def test_registering_needs_automation_then_registers(client, as_principal, principal, monkeypatch):
    as_principal(replace(principal, role="admin"))
    pid = (await client.post("/products", json={"name": "Bread", "price_cents": 6500, "etims_item_class": "5022110801"})).json()["id"]
    monkeypatch.delenv("ETIMS_AUTOMATION", raising=False)
    assert (await client.post(f"/products/{pid}/etims/register")).status_code == 409

    monkeypatch.setenv("ETIMS_AUTOMATION", "1")
    sent = []

    def kra(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"resultCd": "000", "resultMsg": "It is succeeded", "data": None})

    real = etims_module.OscuClient
    monkeypatch.setattr(etims_module, "OscuClient", lambda cfg: real(cfg, transport=httpx.MockTransport(kra)))
    out = (await client.post(f"/products/{pid}/etims/register")).json()
    assert out["etims_item_code"] == "KE2NTU0000001" and out["etims_registered_at"]
    path, body = sent[0]
    assert path.endswith("/saveItem") and body["itemCd"] == "KE2NTU0000001" and body["taxTyCd"] == "B" and body["dftPrc"] == 65.0

    noclass = (await client.post("/products", json={"name": "Tea"})).json()["id"]
    assert (await client.post(f"/products/{noclass}/etims/register")).status_code == 422
