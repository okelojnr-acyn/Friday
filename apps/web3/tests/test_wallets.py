"""Exercises apps/web3 against a FakeProvider standing in for Acyn
Wallet's real Partner API -- these tests never make a network call, and
never hit the real wallet-api.acyninnovation.com. Response shapes here
mirror the real Acyn Wallet API (C:/dev/acyn-wallet/api/src/routes/
partners.ts and masterWalletService.ts/iso20022CreditTransferService.ts)
closely enough that AcynWalletProvider's real implementation is the thing
actually exercised by `app.main`'s call sites -- only the HTTP transport
is faked.
"""

from app import main


class FakeProvider:
    def __init__(self, config):
        self.config = config

    async def get_wallet_info(self):
        return {"address": "0xTREASURY", "defaultNetwork": "base-sepolia", "networks": [{"network": "base-sepolia"}]}

    async def get_balance(self, network=None, token=None):
        return {"network": network, "balances": [{"currency": "ETH", "balance": "0.5"}]}

    async def request_payout(self, to_address, currency, amount, network, reason):
        return {
            "id": "send-1",
            "status": "pending",
            "toAddress": to_address,
            "currency": currency,
            "amount": amount,
            "network": network,
            "reason": reason,
        }

    async def get_payout_status(self, payout_id):
        return {"id": payout_id, "status": "approved"}

    async def submit_credit_transfer(self, message):
        return {"id": "ct-1", "status": "PDNG", "currency": "USD", "amount": "100"}

    async def get_credit_transfer_status(self, transfer_id):
        return {"id": transfer_id, "status": "ACSC"}


async def _fake_config(org_id, provider):
    return {"api_key": "pk_test_123"}


def _connect(monkeypatch):
    monkeypatch.setattr(main, "get_integration_config", _fake_config)
    monkeypatch.setattr(main, "AcynWalletProvider", FakeProvider)


async def test_refresh_wallets_upserts_cached_balance(client, monkeypatch):
    _connect(monkeypatch)
    resp = await client.post("/wallets/refresh")
    assert resp.status_code == 200
    wallets = resp.json()
    assert len(wallets) == 1
    assert wallets[0]["network"] == "base-sepolia"
    assert wallets[0]["balance"] == "0.5"

    listed = (await client.get("/wallets")).json()
    assert len(listed) == 1


async def test_payout_requires_a_connected_provider(client, monkeypatch):
    async def _empty_config(org_id, provider):
        return {}

    monkeypatch.setattr(main, "get_integration_config", _empty_config)
    resp = await client.post(
        "/transactions/payout",
        json={"to_address": "0xabc", "currency": "ETH", "amount": "1", "network": "base-sepolia"},
    )
    assert resp.status_code == 400


async def test_request_payout_creates_pending_transaction_then_polls_status(client, monkeypatch):
    _connect(monkeypatch)
    resp = await client.post(
        "/transactions/payout",
        json={
            "to_address": "0xabc",
            "currency": "ETH",
            "amount": "1",
            "network": "base-sepolia",
            "reason": "vendor payment",
        },
    )
    assert resp.status_code == 201
    txn = resp.json()
    assert txn["kind"] == "payout"
    assert txn["status"] == "pending"
    assert txn["external_id"] == "send-1"

    refreshed = await client.post(f"/transactions/{txn['id']}/refresh-status")
    assert refreshed.json()["status"] == "approved"


async def test_submit_credit_transfer_creates_transaction(client, monkeypatch):
    _connect(monkeypatch)
    resp = await client.post(
        "/transactions/credit-transfer", json={"message": {"GrpHdr": {"MsgId": "m1"}, "CdtTrfTxInf": {}}}
    )
    assert resp.status_code == 201
    txn = resp.json()
    assert txn["kind"] == "credit_transfer"
    assert txn["status"] == "PDNG"
    assert txn["external_id"] == "ct-1"
