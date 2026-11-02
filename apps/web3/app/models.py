import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Wallet(Base):
    """A cached mirror of one network's treasury balance on the org's
    connected wallet provider (Acyn Wallet, today). Refreshed on demand
    (`POST /wallets/refresh`), never polled on a schedule -- consistent
    with "no message broker, no cron" elsewhere in Friday. The provider
    (Acyn Wallet, via Turnkey custody) is the source of truth; this table
    exists so the dashboard has something to render without an API round
    trip on every page load."""

    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="acyn_wallet")
    network: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Stored as text, not a numeric column: on-chain balances are
    # provider-formatted decimal strings (e.g. "0.042100000000000000"),
    # and round-tripping them through a float/Decimal column risks
    # precision loss this app has no business introducing.
    balance: Mapped[str] = mapped_column(Text, nullable=False, default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


TRANSACTION_KINDS = ("payout", "credit_transfer")


class Transaction(Base):
    """A payout request this org made, or an inbound ISO 20022-shaped
    credit transfer it submitted -- see AcynWalletProvider.request_payout
    / submit_credit_transfer. Neither ever moves funds synchronously on
    the provider side; `status` is refreshed by polling
    (`POST /transactions/{id}/refresh-status`), not pushed. Deliberately
    free-text, not a CHECK-constrained enum: a payout's status vocabulary
    ('pending'/'approved'/'rejected') and a credit transfer's
    ('PDNG'/'ACSP'/'ACSC'/'RJCT', per Acyn Wallet's pacs.002 status
    codes) are genuinely different per `kind`."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    amount: Mapped[str] = mapped_column(Text, nullable=False, default="0")
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="")
    network: Mapped[str] = mapped_column(Text, nullable=False, default="")
    to_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
