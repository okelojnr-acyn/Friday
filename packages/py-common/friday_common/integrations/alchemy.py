"""Alchemy adapter -- STUB. For most deployments you don't need this
file: `acyn_wallet.py` already goes through Acyn Wallet, which uses
Alchemy for all its on-chain reads/writes (see
`C:/dev/acyn-wallet/README.md`). Build a direct `OnChainProvider` here
only if you're bypassing Acyn Wallet and talking to a chain yourself.

To complete this: Alchemy (https://docs.alchemy.com) is a JSON-RPC
endpoint per network, URL-keyed (`api_key` below is the path segment in
`https://{network}.g.alchemy.com/v2/{api_key}`), not a header. `get_balance`
is the standard `eth_getBalance` RPC method; `get_transaction` is
`eth_getTransactionByHash`. See INTEGRATIONS.md#alchemy.
"""

from .base import OnChainProvider


class AlchemyProvider(OnChainProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]

    async def get_balance(self, address: str, network: str) -> dict:
        raise NotImplementedError(
            "Alchemy adapter is a stub -- see INTEGRATIONS.md#alchemy and this file's docstring"
        )

    async def get_transaction(self, tx_hash: str, network: str) -> dict:
        raise NotImplementedError(
            "Alchemy adapter is a stub -- see INTEGRATIONS.md#alchemy and this file's docstring"
        )
