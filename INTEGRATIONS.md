# Integrations

Friday connects to the tools a real business already uses -- payments,
chat, calendars, a BaaS, and Web3 -- through one small, consistent
pattern instead of a bespoke integration per provider:

1. An org admin pastes an API key (or webhook URL, or key pair -- whatever
   that provider needs) into **Settings > Integrations**
   (`web/src/shell/IntegrationsSettingsPage.tsx`). That gets stored as a
   JSON blob per `(org, provider)` in the kernel's
   `core.integration_credentials` table (`kernel/internal/integrations`).
2. An app fetches that config with one call --
   `friday_common.get_integration_config(org_id, provider)` -- which
   returns `{}` if the org never connected it. Never raises; an
   unconfigured provider just means "this feature isn't available for
   this org," the same posture `web/src/lib/inventory.ts`'s product-
   catalog fetch already uses for "Inventory isn't installed."
3. An **adapter** (`packages/py-common/friday_common/integrations/*.py`)
   wraps that provider's actual API behind one of a handful of small
   interfaces (`base.py`): `PaymentProvider`, `ChatProvider`,
   `EmailProvider`, `CalendarProvider`, `WalletProvider`,
   `OnChainProvider`, `CustodyProvider`, `OnOffRampProvider`,
   `BaaSProvider`. An app's call site depends on the *interface*, not the
   vendor -- swapping Stripe for Paystack in a deployment is a config
   change, not a code change.

Every provider below is one of two things:

- **Code-ready** -- a real adapter making real HTTP calls, with test
  coverage. Stripe, Slack, and Acyn Wallet are code-ready today.
- **Stub** -- the same interface, a `NotImplementedError` body, and a
  docstring describing exactly what to fill in. **If you're a coding
  agent being asked to wire one of these up**: open the stub file first,
  read its docstring, then copy the shape of the nearest code-ready
  adapter (`stripe.py` for anything payment-shaped, `acyn_wallet.py` for
  anything wallet-shaped) rather than inventing a new pattern. The
  config dict's keys are already decided (see each section below) --
  don't rename them without also updating
  `IntegrationsSettingsPage.tsx`'s matching `ProviderDescriptor`.

## Payments

### Stripe -- code-ready

- Adapter: `friday_common/integrations/stripe.py` (`StripeProvider`).
- Config: `secret_key` (`sk_test_...` / `sk_live_...`), `webhook_secret`
  (`whsec_...`, from the Stripe Dashboard's webhook endpoint settings).
- Call site: `apps/invoicing/app/main.py`'s `pay_with_card` (creates a
  PaymentIntent for an invoice's balance) and
  `apps/invoicing/app/webhooks.py`'s `stripe_webhook` (marks the invoice
  paid once Stripe confirms it). Frontend: `web/src/apps/invoicing/
  PayWithCardPanel.tsx` loads Stripe.js and mounts a real card Element.
- **Deployment note**: `stripe_webhook` lives at
  `/external/webhooks/stripe` and deliberately *isn't* behind the
  kernel's JWT gateway (Stripe can't carry a Friday session token). A
  production deployment needs to route Stripe's webhook calls straight
  to the invoicing service's `/external/webhooks/stripe`, bypassing the
  kernel for that one path (e.g. a separate ingress rule, or exposing
  that one path on the invoicing service directly). See that function's
  own doc comment for the signature-verification trust model this uses
  instead of a bearer token.

### Paystack -- stub

- Adapter: `friday_common/integrations/paystack.py` (`PaystackProvider`).
- Config: `secret_key`.
- Paystack's REST API is close enough to Stripe's shape that `stripe.py`
  is a near-literal template -- see the stub's own docstring for the
  three concrete differences (auth header style, endpoint paths, webhook
  signature scheme).

### Pesapal -- stub

- Adapter: `friday_common/integrations/pesapal.py` (`PesapalProvider`).
- Config: `consumer_key`, `consumer_secret`.
- OAuth-token-based, not a static secret key -- the stub's docstring
  covers the token exchange and the one piece of real logic it still
  needs (caching the short-lived bearer token).

## Notifications

### Slack -- code-ready

- Adapter: `friday_common/integrations/slack.py` (`SlackProvider`).
- Config: `webhook_url` (an Incoming Webhook URL from
  `https://api.slack.com/apps` -> an app -> "Incoming Webhooks").
- Call site: `apps/crm/app/main.py`'s `_notify_slack`, fired on an
  opportunity moving to "won" or "lost". A new notification elsewhere
  follows the same three lines: fetch the org's `slack` config, skip if
  unconfigured, call `SlackProvider(config).notify(text)` inside a
  `try/except` so a notification failure never fails the request that
  triggered it.

### Resend -- code-ready

- Adapter: `friday_common/integrations/resend.py` (`ResendProvider`,
  implementing the new `EmailProvider` interface).
- Config: `api_key` (`re_...`, from https://resend.com/api-keys);
  `from_email` is optional and defaults to Resend's own shared sending
  domain (`onboarding@resend.dev`) so an org can send real email the
  moment they paste a key, before verifying their own sending domain.
- This is deliberately separate from the kernel's own `kernel/internal/
  mail` package (plain SMTP, already works against Resend's SMTP relay
  too -- see `.env.example`'s `SMTP_HOST` block). That one is the
  *platform's* mail, used only for the passwordless-login OTP, and is
  configured once per deployment, not per org. `ResendProvider` is for
  apps emailing an org's *customers* -- bring-your-own-credentials, same
  as Stripe or Slack, connected from Settings > Integrations like any
  other provider.
- Call site: `apps/invoicing/app/main.py`'s `_email_invoice`, fired from
  `set_invoice_status` the moment an invoice first moves to "sent". Best
  effort, same posture as `_notify_slack`: no connected Resend config, or
  no email on the customer record, just means no email goes out -- it
  never fails the status update itself.

## Scheduling

### Calendly -- stub

- Adapter: `friday_common/integrations/calendly.py` (`CalendlyProvider`).
- Config: `api_key` (a personal access token from
  `https://developer.calendly.com`).
- Calendly is scheduling-*link*-driven, not create-event-driven -- the
  stub's docstring flags that `create_event` needs a different shape
  than a literal event POST before you implement it.

### Google Calendar -- code-ready

- Adapter: `friday_common/integrations/google_calendar.py`
  (`GoogleCalendarProvider`).
- Config: `client_id`, `client_secret`, `refresh_token`. Unlike every
  other provider in this doc, `refresh_token` is never pasted in by
  hand -- it's obtained through a real OAuth2 consent flow.
- To connect: in Google Cloud Console, create an OAuth client (any
  project), enable the Calendar API, add
  `{KERNEL_PUBLIC_URL}/orgs/integrations/google_calendar/oauth/callback`
  as an Authorized redirect URI (this is the kernel's own callback, not
  per-org -- see `.env.example`'s `KERNEL_PUBLIC_URL`), then in Settings
  -> Integrations -> Google Calendar, paste that client's `client_id`/
  `client_secret`, Save, then click **Connect with Google** and complete
  the consent screen. The kernel
  (`kernel/internal/integrations/google_oauth.go`) handles the redirect,
  code exchange, and storing the resulting `refresh_token` -- nothing to
  paste manually.
- If a deployed instance's `KERNEL_PUBLIC_URL` is ever wrong, the
  redirect_uri sent to Google won't match what's registered in Cloud
  Console and the consent flow fails at Google's end, not silently.

## BaaS

### MongoDB Atlas -- stub

- Adapter: `friday_common/integrations/atlas.py` (`AtlasProvider`).
- Config: `public_key`, `private_key`, `project_id`.
- Most forks that just want managed Postgres instead of self-hosted
  don't need this file at all -- point `DATABASE_URL` at a managed
  instance, no code change. This adapter is only for Atlas's *extra*
  services (App Services functions/triggers, Atlas Search) beyond "a
  database."

## Market data

### CoinGecko -- code-ready, no credential required

- Adapter: `friday_common/integrations/coingecko.py` (`CoinGeckoProvider`,
  implementing `MarketDataProvider`).
- Config: entirely optional. `watchlist` (a list of CoinGecko coin ids)
  defaults to `["bitcoin", "ethereum", "solana"]` if never set; `api_key`
  switches to CoinGecko's paid Pro tier (higher rate limits) if a
  deployment needs it.
- Call site: `apps/web3/app/main.py`'s `/market/prices` and
  `/market/trending` -- Web3's other mini-app alongside the Acyn
  Wallet-backed Treasury one (`web/src/apps/web3/MarketPage.tsx`). Web3
  isn't just a wallet; it's a small surface for Web3-shaped mini-apps,
  and Market is the first one that isn't custody-related.
- Editing the watchlist happens on the Market page itself, not Settings
  > Integrations (the watchlist is a list, not a single string field,
  so it doesn't fit that screen's generic text-input form — see
  `IntegrationsSettingsPage.tsx`'s `ProviderCard` for why its save merges
  into the existing config instead of replacing it: exactly so editing
  an unrelated field there, like a Pro API key, can never clobber a
  watchlist saved from the Market page).

## Web3

### Acyn Wallet -- code-ready (the recommended path for the wallet mini-app)

- Adapter: `friday_common/integrations/acyn_wallet.py`
  (`AcynWalletProvider`, implementing `WalletProvider`).
- Config: `api_key` (a partner API key -- `pk_live_...`), optional
  `base_url` (defaults to `https://wallet-api.acyninnovation.com`).
- **Setup**: create a business account at Acyn Wallet, complete
  verification, generate a partner API key from its admin console's
  Partner API screen, paste it into `apps/web3`'s Treasury panel
  ("Connect Acyn Wallet") or Settings > Integrations > Acyn Wallet --
  same shape as connecting Stripe or Slack.
- What you get: a real custodial business wallet, with Turnkey custody,
  Alchemy on-chain reads, and Bridge settlement verification already
  wired in on Acyn Wallet's side. Friday's `apps/web3` never talks to
  Turnkey/Alchemy/Bridge directly on this path -- see
  `kernel/internal/registry/registry.go`'s `web3` entry and
  `apps/web3/app/main.py` for the resources (`Wallet`, `Transaction`)
  and actions (balance refresh, payout request, ISO 20022-shaped credit
  transfer submission) this unlocks.
- This is the path almost every deployment should take. The three
  adapters below exist for the smaller case: a fork building its own
  custody stack instead of going through Acyn Wallet.

### Alchemy -- stub (direct on-chain reads, bypasses Acyn Wallet)

- Adapter: `friday_common/integrations/alchemy.py` (`AlchemyProvider`,
  implementing `OnChainProvider`).
- Config: `api_key` (used as a URL path segment, not a header -- see the
  stub's docstring).
- Only needed if you're not using Acyn Wallet.

### Turnkey -- stub (direct custody, bypasses Acyn Wallet)

- Adapter: `friday_common/integrations/turnkey.py` (`TurnkeyProvider`,
  implementing `CustodyProvider`).
- Config: `api_public_key`, `api_private_key`, `organization_id`.
- Turnkey authenticates with a signed request stamp, not a bearer token
  -- real cryptographic work to get right. Read Turnkey's own SDKs for
  the canonical stamp format before implementing this; don't hand-roll
  it from the docstring alone.
- Only needed if you're not using Acyn Wallet.

### Bridge -- stub (direct on/off-ramp, bypasses Acyn Wallet)

- Adapter: `friday_common/integrations/bridge.py` (`BridgeProvider`,
  implementing `OnOffRampProvider`).
- Config: `api_key`.
- Only needed if you're not using Acyn Wallet, which already wires
  Bridge in as its own settlement-verification source.

## Adding a new provider

1. Pick (or add) a category interface in `base.py`.
2. Add a `<provider>.py` file implementing it. Code-ready if you have
   real credentials to test against; otherwise a stub following the
   shape above -- `NotImplementedError` bodies, a docstring stating the
   config keys and the real endpoint shapes.
3. Export it from `integrations/__init__.py`.
4. Add a `ProviderDescriptor` to `IntegrationsSettingsPage.tsx`'s
   `PROVIDERS` array (icon, category, config fields) so an org can
   actually connect it from the UI.
5. Document it in this file, in the matching category section.
