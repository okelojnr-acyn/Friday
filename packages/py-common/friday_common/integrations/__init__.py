"""Third-party integration adapters, one small interface per category
(payments, chat, calendar, wallet, on-chain, custody, on/off-ramp, BaaS) so
an app calls `PaymentProvider.charge` without caring whether the org
connected Stripe or Paystack underneath. See INTEGRATIONS.md for the full
provider list, which ones are code-ready vs. stubs, and exactly what each
provider's stored `config` dict needs to contain.

`get_integration_config` is the one function every adapter's call site
needs: it fetches an org's stored config for one provider from the
kernel's credential store, returning `{}` if the org hasn't connected
that provider (never raises -- callers treat an unconfigured provider as
"feature not available for this org", same posture as
`web/src/lib/inventory.ts`'s best-effort product-catalog fetch).
"""

from .acyn_wallet import AcynWalletProvider
from .alchemy import AlchemyProvider
from .atlas import AtlasProvider
from .base import (
    BaaSProvider,
    CalendarProvider,
    ChatProvider,
    CustodyProvider,
    EmailProvider,
    MarketDataProvider,
    OnChainProvider,
    OnOffRampProvider,
    PaymentProvider,
    WalletProvider,
)
from .bridge import BridgeProvider
from .calendly import CalendlyProvider
from .coingecko import CoinGeckoProvider
from .config import get_integration_config
from .google_calendar import GoogleCalendarProvider
from .paystack import PaystackProvider
from .pesapal import PesapalProvider
from .resend import ResendProvider
from .slack import SlackProvider
from .stripe import StripeProvider
from .turnkey import TurnkeyProvider

__all__ = [
    "AcynWalletProvider",
    "AlchemyProvider",
    "AtlasProvider",
    "BaaSProvider",
    "BridgeProvider",
    "CalendarProvider",
    "CalendlyProvider",
    "ChatProvider",
    "CoinGeckoProvider",
    "CustodyProvider",
    "EmailProvider",
    "GoogleCalendarProvider",
    "MarketDataProvider",
    "OnChainProvider",
    "OnOffRampProvider",
    "PaymentProvider",
    "PaystackProvider",
    "PesapalProvider",
    "ResendProvider",
    "SlackProvider",
    "StripeProvider",
    "TurnkeyProvider",
    "WalletProvider",
    "get_integration_config",
]
