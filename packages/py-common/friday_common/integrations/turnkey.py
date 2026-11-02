"""Turnkey adapter -- STUB. For most deployments you don't need this
file: `acyn_wallet.py` already goes through Acyn Wallet, which custodies
every wallet through its own Turnkey sub-organization (see
`C:/dev/acyn-wallet/README.md`) -- no raw private key ever needs to touch
a Friday deployment's own database. Build a direct `CustodyProvider` here
only if you're bypassing Acyn Wallet and provisioning your own wallets.

To complete this: Turnkey (https://docs.turnkey.com) authenticates
requests with a P-256 keypair signature (`api_public_key`/
`api_private_key` below), not a bearer token -- every request body is
signed with `X-Stamp`. `create_wallet` maps to `POST
/public/v1/submit/create_wallet`, `sign_transaction` to `POST
/public/v1/submit/sign_transaction`. This request-signing step is
real cryptographic work to get right (see Turnkey's own SDKs for the
canonical stamp format) -- don't hand-roll it without reading their docs
closely. See INTEGRATIONS.md#turnkey.
"""

from .base import CustodyProvider


class TurnkeyProvider(CustodyProvider):
    def __init__(self, config: dict):
        self.api_public_key = config["api_public_key"]
        self.api_private_key = config["api_private_key"]
        self.organization_id = config["organization_id"]

    async def create_wallet(self, label: str) -> dict:
        raise NotImplementedError(
            "Turnkey adapter is a stub -- see INTEGRATIONS.md#turnkey and this file's docstring"
        )

    async def sign_transaction(self, wallet_id: str, unsigned_tx: dict) -> dict:
        raise NotImplementedError(
            "Turnkey adapter is a stub -- see INTEGRATIONS.md#turnkey and this file's docstring"
        )
