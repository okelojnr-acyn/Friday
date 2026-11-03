import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    resource,
)
from friday_common.integrations import AcynWalletProvider, CoinGeckoProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Transaction, Wallet
from .schemas import CreditTransferSubmit, PayoutRequest, TransactionOut, WalletOut

resource(
    ResourceSpec(
        name="wallet",
        app="web3",
        label="Wallet",
        label_plural="Wallets",
        views=("list",),
        search_fields=("network", "currency"),
        fields=(
            FieldSpec("network", "Network", "text", required=True),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("address", "Address", "text"),
            FieldSpec("balance", "Balance", "text"),
            FieldSpec("updated_at", "Last synced", "datetime"),
        ),
    )
)

resource(
    ResourceSpec(
        name="transaction",
        app="web3",
        label="Transaction",
        label_plural="Transactions",
        views=("list",),
        search_fields=("external_id", "to_address"),
        fields=(
            FieldSpec("kind", "Kind", "select", options=("payout", "credit_transfer"), required=True),
            FieldSpec("status", "Status", "text"),
            FieldSpec("amount", "Amount", "text"),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("network", "Network", "text"),
            FieldSpec("to_address", "To", "text", list_visible=False),
            FieldSpec("reason", "Reason", "text", list_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-web3")

wallets_router = APIRouter(prefix="/wallets", tags=["wallets"])
transactions_router = APIRouter(prefix="/transactions", tags=["transactions"])
market_router = APIRouter(prefix="/market", tags=["market"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def _provider(principal: Principal) -> AcynWalletProvider:
    """Every route that talks to Acyn Wallet goes through this -- a
    missing/disconnected integration is a clean 400 ("connect it in
    Settings"), not an exception leaking out of the provider's own
    `config["api_key"]` KeyError."""
    config = await get_integration_config(principal.org_id, "acyn_wallet")
    if not config.get("api_key"):
        raise HTTPException(400, "Acyn Wallet is not connected -- add an API key in Settings > Integrations")
    return AcynWalletProvider(config)


@wallets_router.get("", response_model=list[WalletOut])
async def list_wallets(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Wallet).where(Wallet.org_id == _org(principal)).order_by(Wallet.network, Wallet.currency)
    )
    return rows.scalars().all()


@wallets_router.post("/refresh", response_model=list[WalletOut])
async def refresh_wallets(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Pulls the treasury's registered networks and per-network balances
    from Acyn Wallet and upserts the cached `Wallet` rows -- the
    "Refresh" button on the Treasury panel, not a background poll (see
    ARCHITECTURE.md's "no message broker" posture)."""
    provider = await _provider(principal)
    info = await provider.get_wallet_info()
    address = info.get("address", "")
    now = datetime.now(UTC)

    for net in info.get("networks", []):
        network = net["network"]
        balances = (await provider.get_balance(network=network)).get("balances", [])
        for b in balances:
            existing = await session.execute(
                select(Wallet).where(
                    Wallet.org_id == _org(principal),
                    Wallet.network == network,
                    Wallet.currency == b["currency"],
                )
            )
            wallet = existing.scalar_one_or_none()
            if wallet is None:
                wallet = Wallet(org_id=_org(principal), network=network, currency=b["currency"])
                session.add(wallet)
            wallet.address = address
            wallet.balance = str(b["balance"])
            wallet.updated_at = now

    await session.commit()
    rows = await session.execute(select(Wallet).where(Wallet.org_id == _org(principal)).order_by(Wallet.network))
    return rows.scalars().all()


@transactions_router.get("", response_model=list[TransactionOut])
async def list_transactions(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Transaction).where(Transaction.org_id == _org(principal)).order_by(Transaction.created_at.desc())
    )
    return rows.scalars().all()


@transactions_router.post("/payout", response_model=TransactionOut, status_code=201)
async def request_payout(
    body: PayoutRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    provider = await _provider(principal)
    result = await provider.request_payout(
        to_address=body.to_address, currency=body.currency, amount=body.amount, network=body.network, reason=body.reason
    )
    now = datetime.now(UTC)
    txn = Transaction(
        org_id=_org(principal),
        kind="payout",
        external_id=result["id"],
        status=result.get("status", "pending"),
        amount=result.get("amount", body.amount),
        currency=result.get("currency", body.currency),
        network=result.get("network", body.network),
        to_address=result.get("toAddress", body.to_address),
        reason=result.get("reason", body.reason),
        created_at=now,
        updated_at=now,
    )
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return txn


@transactions_router.post("/credit-transfer", response_model=TransactionOut, status_code=201)
async def submit_credit_transfer(
    body: CreditTransferSubmit,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    provider = await _provider(principal)
    result = await provider.submit_credit_transfer(body.message)
    now = datetime.now(UTC)
    txn = Transaction(
        org_id=_org(principal),
        kind="credit_transfer",
        external_id=result["id"],
        status=result.get("status", "PDNG"),
        amount=result.get("amount", ""),
        currency=result.get("currency", ""),
        reason=result.get("decisionReason") or "",
        created_at=now,
        updated_at=now,
    )
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return txn


async def _get_owned_transaction(session: AsyncSession, principal: Principal, txn_id: uuid.UUID) -> Transaction:
    txn = await session.get(Transaction, txn_id)
    if txn is None or str(txn.org_id) != principal.org_id:
        raise HTTPException(404, "transaction not found")
    return txn


@transactions_router.post("/{txn_id}/refresh-status", response_model=TransactionOut)
async def refresh_transaction_status(
    txn_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    txn = await _get_owned_transaction(session, principal, txn_id)
    provider = await _provider(principal)
    result = (
        await provider.get_payout_status(txn.external_id)
        if txn.kind == "payout"
        else await provider.get_credit_transfer_status(txn.external_id)
    )
    txn.status = result.get("status", txn.status)
    txn.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(txn)
    return txn


@market_router.get("/prices")
async def market_prices(
    ids: str | None = None,
    principal: Principal = Depends(get_current_principal),
):
    """The Market mini-app's one read -- Web3 isn't only the Acyn
    Wallet-backed Treasury mini-app; this is the other one, live crypto
    prices via CoinGecko's free public API. `ids` is a comma-separated
    list of CoinGecko coin ids; falls back to the org's saved watchlist
    (Settings > Integrations > CoinGecko), or a small sensible default
    if that was never configured either -- see CoinGeckoProvider's
    DEFAULT_WATCHLIST. No API key required for this to work at all."""
    config = await get_integration_config(principal.org_id, "coingecko")
    provider = CoinGeckoProvider(config)
    coin_ids = ids.split(",") if ids else provider.watchlist
    return await provider.get_prices(coin_ids)


@market_router.get("/trending")
async def market_trending(principal: Principal = Depends(get_current_principal)):
    config = await get_integration_config(principal.org_id, "coingecko")
    return await CoinGeckoProvider(config).get_trending()


app.include_router(wallets_router)
app.include_router(transactions_router)
app.include_router(market_router)
