# Friday — Status & Roadmap

This file is "what's done" and "what's next" for Friday itself (the
CRM/invoicing/projects CaaS product). Read this first in a new session
before touching code. `PRD.md` and `ARCHITECTURE.md` are the stable
reference docs (what Friday is, how it's built); this file is the
changing, session-to-session status layer on top of them — update it
whenever you finish or start something nontrivial, don't let it drift.

Friday runs as a tenant on **Friday Host**
(`github.com/okelojnr-acyn/friday-cloud-labs`) — that repo's own
`ROADMAP.md` is the source of truth for the hosting platform itself and
for the dogfood-deployment history (what's live, which servers, which
DNS/Vercel steps happened). This file stays scoped to Friday's own
product code.

---

## Status snapshot — 2026-11-09

**Deployed today**: kernel + crm + invoicing run as real tenant
containers on Friday Host (`friday-kernel`/`friday-crm`/`friday-invoicing`),
with the web shell live at `https://friday.fridayhost.dev`. The other
six apps (projects, inventory, web3, accounting, minions, fleets) exist
in the repo and build via the same `infra/python-app.Dockerfile`
pattern, just not deployed as tenant containers yet — not blocked on
anything, just not needed until a dogfood or real-customer workflow
exercises them.

**This session's changes** (commit `065ac3e`, pushed):
- `web/src/ui/TopBar.tsx` — a shortcut straight to
  `https://fridayhost.dev/app`, first item in the top-bar nav group.
- **New `EmailProvider` category + `ResendProvider` adapter**
  (`packages/py-common/friday_common/integrations/resend.py`) — there
  was no email-sending integration at all before this; the only
  existing mail code was `kernel/internal/mail` (plain SMTP, login-OTP
  only, one config per deployment, not per org). Resend is per-org,
  bring-your-own-credentials, same pattern as Stripe/Slack. Wired into
  one real call site: `apps/invoicing/app/main.py`'s
  `set_invoice_status` now emails the customer (best-effort, same
  posture as `_notify_slack`) the moment an invoice first moves to
  "sent," if the org has connected Resend.
- `INSTALL.md` now documents `SMTP_HOST`/etc — it had zero SMTP
  mentions before, so a deployer following that procedure would never
  discover that OTP logins silently no-op into stdout until it's set.
  Clarified that's separate from the new per-org Resend integration.

**Later the same day — Google Calendar OAuth2 (roadmap item #1, done)**:
`GoogleCalendarProvider` is no longer a stub. Added the consent/callback
flow that was the actual gap (`kernel/internal/integrations/google_oauth.go`:
`GoogleOAuthStart`/`GoogleOAuthCallback`, new `POST .../oauth/start` +
`GET .../oauth/callback` routes in `kernel/cmd/kernel/main.go`, the
callback deliberately outside `requireAuth` since no Authorization
header survives Google's redirect — a signed `state` JWT, reusing the
existing session `JWT_SECRET` with its own claims shape, stands in for
auth there instead). New `KERNEL_PUBLIC_URL` env var so the kernel knows
its own externally-reachable URL to build `redirect_uri` identically in
both the authorize and token-exchange steps (documented in
`.env.example` and `INSTALL.md`). Frontend: `IntegrationsSettingsPage.tsx`
got a real "Connect with Google" button (`oauth: true` on that
provider's descriptor) instead of a manual `refresh_token` field, plus a
banner reading the `?google_calendar=connected|error` query param the
callback redirects back with. `google_calendar.py`'s `create_event` is
now real too — plain `httpx`, same posture as `stripe.py`, refreshes an
access token from the stored `refresh_token` on every call. Build-verified
(`go build`/`go vet`, `tsc --noEmit` + `vite build`, `ruff check`) but
**not yet exercised against a real Google Cloud OAuth client** — that's
the one thing to do first next session before trusting this live.

**Later the same day — full product-completeness audit, then POS
identity + real Pesapal checkout shipped.** The user's impression going
in was that Friday was "extremely shallow" (no inventory UI, no POS
production-readiness, no staff traceability, no cross-app integration).
A code-grounded audit found that was **half right**: inventory product
management (add/bulk-add via the UI), POS→inventory stock sync, and
invoice→accounting ledger posting all already work end-to-end — not
assumptions, verified by tracing the actual call paths. The real,
confirmed gaps were narrower: **(1)** POS checkout never called any
payment gateway regardless of what was connected (Pesapal's adapter was
a pure stub), and **(2)** no POS sale could be traced to a specific
minion/staff member. Both are fixed now:

- **Cashier/employee identity on every POS sale and shift** — `Invoice`
  gained `cashier_user_id`/`cashier_email`, `PosShift` gained
  `opened_by_user_id`/`opened_by_email`
  (`apps/invoicing/migrations/0007_pos_identity.sql`), stamped from
  `Principal` (already available, just never persisted) in
  `record_pos_sale`/`return_pos_sale`/`open_pos_shift`. A new
  `employee_sales` table in **Minions**
  (`apps/minions/migrations/0002_employee_sale.sql`) subscribes to
  `invoicing.pos_sale.recorded` (new kernel event-table entry in
  `kernel/internal/gateway/events.go`) and attributes each sale to an
  `Employee` by `user_id`-then-`email`, same resolution logic
  `_resolve_my_employee` already used for self-service — exposed as a
  normal read-only resource, no new frontend code needed.
- **Real Pesapal checkout for POS** — `PesapalProvider`
  (`packages/py-common/friday_common/integrations/pesapal.py`) is no
  longer a stub: token caching, `SubmitOrderRequest`, and
  `GetTransactionStatus` are real. New `POST /pos/sales/pay-with-pesapal`
  creates the sale as `status="pending"` (new status, not exposed as a
  user-settable value) and returns a `redirect_url`; the new
  `/external/webhooks/pesapal` IPN handler is the only thing that marks
  it paid, and only after re-verifying with `GetTransactionStatus` —
  never trusting the callback body, same principle as Stripe's signature
  check. `PosPage.tsx` got a "Mobile Money" button that polls for
  confirmation instead of optimistically clearing the cart (deliberately
  online-only, no offline-queue path for this one). New `APP_PUBLIC_URL`
  env var (invoicing service only) so the adapter can register a real
  IPN callback URL with Pesapal at runtime.
- **Found and documented, not fixed this pass**: neither
  `/external/webhooks/stripe` nor the new `/external/webhooks/pesapal`
  actually has deployment-level routing anywhere in tracked config (see
  Friday Host's own `ROADMAP.md` open-decisions list) — real payments on
  a **deployed** tenant don't work yet for either provider, only in
  local dev where both routes are directly reachable.
- Build-verified end to end (`go build`/`go vet`, `tsc --noEmit` +
  `vite build`, `ruff check`, full pytest collection with 11 new tests
  added) **but not run against a live Postgres** — this machine's Docker
  Desktop wouldn't come up this session (known issue, see memory); the
  new tests themselves were never executed, only confirmed to collect
  and import cleanly. Run `pytest` for real in `apps/invoicing` and
  `apps/minions` first thing next session before trusting this live.

---

## Next up, in order

### 1. Run the new tests for real

Docker wouldn't start this session (see above) — the Pesapal/cashier-
identity work above was verified by syntax/lint/collection and careful
manual tracing (which already caught and fixed two real pre-existing
test regressions the refactor would have silently caused — see
`test_pos_sales.py`/`test_pos_returns.py`'s `app.events.publish_event`
monkeypatch fix), but no test has actually executed against a live DB
yet. Get Postgres up and run both suites before building on top of this.

### 2. POS offline install + biometric cashier verification

The other half of "make POS production-level" the user asked for,
deliberately deferred this session to keep the Pesapal/identity work
reviewable on its own. Confirmed while auditing: the hard pieces already
exist, just disconnected — `pos-engine`'s Rust/WASM layer already has a
real offline sale queue (`OfflineQueue`), and the kernel already has a
real WebAuthn passkey system (`kernel/internal/auth/webauthn.go`), just
wired only to login, not constrained to platform/biometric authenticators,
and with no mid-session "verify this cashier" gate. The PWA manifest/
service-worker scaffolding (`web/vite.config.ts`'s `VitePWA` config) is
also wired exclusively to the separate Minions mini-app (`minions.html`)
— the main shell hosting `PosPage.tsx` registers no service worker at
all today. Needs its own design pass: likely (a) extend `VitePWA`'s
manifest to cover `index.html`, (b) add a WebAuthn re-auth step scoped
to opening a shift or completing a sale, (c) decide whether to constrain
that specific flow to `AuthenticatorAttachment: "platform"` (real
fingerprint/Face ID) vs. leaving it open to security keys too.

### 3. Close the COGS no-op

`apps/accounting`'s `pos_sale_cogs` webhook has never posted a real
entry — `unit_cost_cents` is documented as always `None` in the event
payload (`invoicing.pos_sale.recorded`'s construction in
`apps/invoicing/app/events.py`), even though `InvoiceLine.unit_cost_cents`
itself is already populated when a POS line is rung up from the product
catalog. Margin/profit reporting is silently wrong today as a result —
revenue posts correctly, cost of goods never does. Likely a small fix
(thread the already-captured value through), confirm scope before
starting.

### 4. Decide the fate of the island apps

`projects`, `fleets`, and `web3` publish nothing, subscribe to nothing,
and nothing else references their data (confirmed by a repo-wide grep
for cross-references) — CRM is one-directional (feeds invoicing, nothing
feeds back). Part of the user's "all these apps depend on each other"
complaint. Needs a product decision, not just code: which of these
should actually integrate with the rest (and how), vs. staying
legitimately independent for now.

### 5. Self-serve data import

There's a one-off dev script
(`scripts/host-data-import-template.py`) but nothing in-product for an
org to bring in an Excel sheet or connect an external DB/spreadsheet for
inventory or CRM data — raised explicitly by the user ("we can't connect
it to excel or database that we do have"). Not scoped yet.

### 6. Minions meeting scheduling — unblocked (Google Calendar OAuth2 done)

`GoogleCalendarProvider.create_event` now actually works end-to-end once
an org connects (still **not yet verified against a real Google Cloud
OAuth client** — do that first). Confirmed earlier this session: Minions
has **zero** task/calendar/meeting concept today — only `employee`,
`expense_claim`, `payroll_run`, and the new `employee_sale` resources
exist. `web/src/minions/MyTasksPage.tsx` is a thin read of **Projects'**
`task` resource filtered client-side by `assignee_email`, not a
Minions-owned concept.

Open design question: does "easy meeting scheduling" become a new
Minions-owned resource (e.g. `meeting`, calling
`GoogleCalendarProvider.create_event` on create), or does it extend the
existing cross-app pattern `MyTasksPage` already uses? Needs its own
design pass before code.

### 7. Enterprise-grade invoicing/checkout breadth (generic frontend)

Mirrors Friday Host's own `ROADMAP.md` Increment 6 item 2: `crm`,
`fleets`, and `projects` have **no custom frontend at all**, rendering
purely through the generic `web/src/ui/resource/{ListView,KanbanView,
FormView}.tsx` pattern. Not started.

---

## Open decisions / things to confirm before they block something

- Whether Minions meeting scheduling is a new resource or extends the
  cross-app pattern (see #6 above) — resolve as part of its own design
  pass before writing code.
- Whether POS's biometric cashier gate (item #2) should be constrained
  to platform authenticators specifically, or left open to any WebAuthn
  credential — resolve as part of that design pass.
- Which of `projects`/`fleets`/`web3` (item #4) should actually
  integrate with the rest of the system — a product decision, not a
  technical one.

## Session rules (apply across both Friday and Friday Host)

- **Never run content-revealing commands on secret-bearing files**
  (`cat`/`od`/`type`/`Get-Content` on `.env` or anything piped without a
  redacting filter, raw `curl -v`). Verify a secret by hash/length or by
  testing it functionally, never by printing it.
- **Always typecheck + build the frontend and run the relevant
  `pytest`/`go test` suite before committing** — this session caught a
  real self-inflicted bug (an edit accidentally merging two functions
  together) exactly this way, by diffing test-collection output against
  a clean baseline before trusting a "looks right" edit.
