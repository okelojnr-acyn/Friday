"""Acyn Wallet adapter -- code-ready, and the primary/first-class
`WalletProvider` for `apps/web3`. Acyn Wallet (sibling project,
`C:/dev/acyn-wallet`) is a custodial business wallet that already wraps
Turnkey (custody), Alchemy (on-chain reads), and Bridge (settlement
verification) behind one Partner API key -- see
`C:/dev/acyn-wallet/api/README.md` for the authoritative shape of every
endpoint this adapter calls.

To use this: create a business account on Acyn Wallet, complete
verification, generate a partner API key from its admin console (Partner
API screen), then paste that key into Friday's Settings -> Integrations
-> Acyn Wallet (`api_key` in the stored config) or into `apps/web3`'s
Treasury panel's "Connect" form. No other setup needed -- Friday never
talks to Turnkey/Alchemy/Bridge directly for this path.

Testnet only until Acyn Wallet enables mainnet (`MAINNET_ENABLED=false`
on that side) -- this adapter doesn't know or care, it just calls
whatever `base_url` is configured.
"""

import httpx

from .base import WalletProvider

DEFAULT_BASE_URL = "https://wallet-api.acyninnovation.com"


class AcynWalletProvider(WalletProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", DEFAULT_BASE_URL)

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key}

    async def get_wallet_info(self) -> dict:
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get("/api/v1/partners/wallet-info", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_balance(self, network: str | None = None, token: str | None = None) -> dict:
        params = {k: v for k, v in {"network": network, "token": token}.items() if v}
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get("/api/v1/partners/balance", params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_balance_history(self, network: str | None = None, from_block: int | None = None) -> dict:
        params = {k: str(v) for k, v in {"network": network, "fromBlock": from_block}.items() if v}
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get("/api/v1/partners/balance/history", params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def request_payout(self, to_address: str, currency: str, amount: str, network: str, reason: str) -> dict:
        """Never broadcasts directly -- Acyn Wallet queues this into its
        own dual-control admin approval queue and returns HTTP 202 with
        the pending request, not a completed transfer."""
        body = {"toAddress": to_address, "currency": currency, "amount": amount, "network": network, "reason": reason}
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.post("/api/v1/partners/send", json=body, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_payout_status(self, payout_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get(f"/api/v1/partners/send/{payout_id}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def submit_credit_transfer(self, message: dict) -> dict:
        """`message` is a pacs.008-shaped dict (GrpHdr, CdtTrfTxInf, ... --
        see the Acyn Wallet README's field reference). Recorded as
        pending (PDNG); never auto-credits a wallet on receipt."""
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.post("/api/v1/partners/credit-transfer", json=message, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_credit_transfer_status(self, transfer_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get(f"/api/v1/partners/credit-transfer/{transfer_id}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
