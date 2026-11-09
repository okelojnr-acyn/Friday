"""Category interfaces every integration adapter implements. A category
exists so an app's call site depends on the *category* (PaymentProvider),
never a specific vendor (StripeProvider) -- swapping Stripe for Paystack
in a deployment's config is then a config change, not a code change.
"""

from abc import ABC, abstractmethod


class PaymentProvider(ABC):
    """Stripe, Paystack, Pesapal -- anything that can take a card/mobile
    money payment and later refund it."""

    @abstractmethod
    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        """Start a payment. Returns at minimum an `id` the caller can
        store and later look up; the rest of the shape is provider-specific
        (Stripe returns `client_secret` for the browser to confirm with)."""

    @abstractmethod
    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        """Refund a previously completed payment, in full (omit
        `amount_cents`) or in part."""


class ChatProvider(ABC):
    """Slack, or anything else that can receive a plain-text
    notification -- a won deal, a paid invoice, a low-stock alert."""

    @abstractmethod
    async def notify(self, text: str) -> None: ...


class EmailProvider(ABC):
    """Resend, or anything else that can send a transactional email to a
    customer -- an invoice being sent, a receipt, a meeting invite. Separate
    from the kernel's own `mail` package (plain SMTP, used only for the
    passwordless-login OTP) -- this is per-org, bring-your-own-credentials,
    for apps emailing an org's *customers*, not the platform emailing its
    own users."""

    @abstractmethod
    async def send(self, to: str, subject: str, html: str) -> dict: ...


class CalendarProvider(ABC):
    """Calendly, Google Calendar -- booking links and calendar events."""

    @abstractmethod
    async def create_event(self, title: str, start_iso: str, end_iso: str, attendees: list[str]) -> dict: ...

    @abstractmethod
    async def update_event(self, event_id: str, title: str, start_iso: str, end_iso: str, attendees: list[str]) -> dict:
        """Reschedule/retitle/re-invite an event create_event already made."""

    @abstractmethod
    async def delete_event(self, event_id: str) -> None:
        """Cancel an event create_event already made -- callers use this
        when the thing that scheduled it (e.g. Minions' Meeting) is
        itself deleted, so a canceled meeting doesn't leave a stale
        invite sitting on every attendee's real calendar."""


class WalletProvider(ABC):
    """A custodial business wallet -- Acyn Wallet's Partner API shape
    (see `acyn_wallet.py`), which itself wraps Turnkey custody, Alchemy
    on-chain reads, and Bridge settlement behind one API key. This is the
    interface `apps/web3` is built against."""

    @abstractmethod
    async def get_wallet_info(self) -> dict:
        """Treasury address, registered networks, supported currencies."""

    @abstractmethod
    async def get_balance(self, network: str | None = None, token: str | None = None) -> dict: ...

    @abstractmethod
    async def request_payout(self, to_address: str, currency: str, amount: str, network: str, reason: str) -> dict:
        """Queue a payout request. Never moves funds synchronously -- the
        real Acyn Wallet implementation returns a pending request id to
        poll, not a completed transfer."""

    @abstractmethod
    async def get_payout_status(self, payout_id: str) -> dict: ...

    @abstractmethod
    async def submit_credit_transfer(self, message: dict) -> dict:
        """Submit an inbound, ISO 20022 pacs.008-shaped credit transfer
        message. Never auto-credits a wallet -- returns a pending record
        id to poll."""

    @abstractmethod
    async def get_credit_transfer_status(self, transfer_id: str) -> dict: ...


class OnChainProvider(ABC):
    """Direct on-chain reads/writes (Alchemy) -- only needed if a fork
    builds its own custody instead of going through Acyn Wallet's
    WalletProvider."""

    @abstractmethod
    async def get_balance(self, address: str, network: str) -> dict: ...

    @abstractmethod
    async def get_transaction(self, tx_hash: str, network: str) -> dict: ...


class CustodyProvider(ABC):
    """Key custody / signing (Turnkey) -- only needed if a fork builds its
    own wallet provisioning instead of going through Acyn Wallet."""

    @abstractmethod
    async def create_wallet(self, label: str) -> dict: ...

    @abstractmethod
    async def sign_transaction(self, wallet_id: str, unsigned_tx: dict) -> dict: ...


class OnOffRampProvider(ABC):
    """Fiat <-> crypto on/off-ramp (Bridge) -- only needed if a fork
    builds its own settlement instead of going through Acyn Wallet, which
    already wires Bridge in as its settlement verification source."""

    @abstractmethod
    async def create_transfer(self, amount: str, currency: str, destination: dict) -> dict: ...

    @abstractmethod
    async def get_transfer_status(self, transfer_id: str) -> dict: ...


class MarketDataProvider(ABC):
    """Price/trending data for crypto assets (CoinGecko) -- the other
    half of Web3 beyond a business wallet. Not every Web3 mini-app needs
    a wallet provider at all; this one is read-only market data, no
    custody, no API key required for the free tier."""

    @abstractmethod
    async def get_prices(self, coin_ids: list[str], vs_currency: str = "usd") -> dict: ...

    @abstractmethod
    async def get_trending(self) -> list[dict]: ...


class BaaSProvider(ABC):
    """A managed backend-as-a-service (MongoDB Atlas, etc.) offering more
    than "just point DATABASE_URL at it" -- e.g. Atlas App Services
    functions/triggers. Most forks that just want managed Postgres don't
    need this at all: point `DATABASE_URL` at the managed instance and
    skip this interface entirely."""

    @abstractmethod
    async def health_check(self) -> dict: ...
