"""Bridge adapter -- STUB. For most deployments you don't need this file:
`acyn_wallet.py` already goes through Acyn Wallet, which wires Bridge in
as its own settlement-verification source (see
`C:/dev/acyn-wallet/api/README.md`'s credit-transfer section). Build a
direct `OnOffRampProvider` here only if you're bypassing Acyn Wallet
entirely and standing up your own custody/settlement stack.

To complete this: Bridge's API (https://apidocs.bridge.xyz) is API-key
authenticated (`api_key` below, sent as `Api-Key` header). `create_transfer`
maps to `POST /v0/transfers`, `get_transfer_status` to `GET
/v0/transfers/{id}`. See INTEGRATIONS.md#bridge.
"""

from .base import OnOffRampProvider


class BridgeProvider(OnOffRampProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]

    async def create_transfer(self, amount: str, currency: str, destination: dict) -> dict:
        raise NotImplementedError("Bridge adapter is a stub -- see INTEGRATIONS.md#bridge and this file's docstring")

    async def get_transfer_status(self, transfer_id: str) -> dict:
        raise NotImplementedError("Bridge adapter is a stub -- see INTEGRATIONS.md#bridge and this file's docstring")
