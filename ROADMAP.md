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

**Later the same day — webhook-routing correction, then POS offline
install + biometric clock-in shipped.** The "neither Stripe's nor
Pesapal's external webhook has deployment routing" gap noted above
turned out to be wrong — written before actually reading Friday Host's
`api/internal/ingress/handlers.go`. `POST /servers/{id}/expose` already
exposes *any* tenant container (not just a kernel) to a real public
hostname; since `invoicing` runs as its own tenant container, it's
already eligible. No code to build, just corrected deployment docs
(`INSTALL.md`/`INTEGRATIONS.md` here, and Friday Host's own `ROADMAP.md`).

Then the other half of "make POS production-level": offline install +
biometric cashier clock-in. Confirmed before building anything: the hard
pieces already existed, disconnected — `pos-engine`'s offline sale queue,
and the kernel's discoverable WebAuthn passkey login
(`loginWithPasskey`/`addPasskey` in `web/src/lib/auth.tsx`). Three design
forks resolved with the user first: **shared register device** (not
personal devices), **POS gets its own installable mini-app** (not the
whole main shell), **platform authenticators only**.

- **POS is now its own mini-app** — `web/pos.html` +
  `web/src/pos-main.tsx` + `web/src/apps/pos/PosApp.tsx`, mirroring
  Minions' existing pattern exactly. The old ungated `/pos` route inside
  the main shell (`App.tsx`) is gone — reachable only via the dashboard
  tile's external link to `/pos.html` now, same way Minions isn't a
  route inside the main shell either.
- **Biometric clock-in, not per-sale re-verification** —
  `web/src/apps/pos/PosClockIn.tsx` gates the register behind a scan.
  Reuses `loginWithPasskey()` completely unchanged: on a shared device,
  a fingerprint scan has to *identify* who's using it right now, not
  just confirm a session that's already there, and the existing
  discoverable ceremony already does exactly that — it overwrites the
  active session with a fresh JWT for whoever scanned in, so every POS
  request afterward (including last session's `cashier_user_id`
  stamping) is already correctly attributed with zero backend changes.
  "Clocked in" is in-memory only, reset on every page load, deliberately
  — walking up to the register always demands a fresh scan.
- **Platform-only, registration-time only** —
  `kernel/internal/auth/handlers.go`'s `PasskeyRegisterOptions` gained
  `?purpose=pos`, constraining `AuthenticatorAttachment` to `platform`
  (verified against the real go-webauthn v0.18.2 API via `go doc`, not
  guessed) for POS's own fingerprint registration specifically — the
  general "add a passkey to my account" flow is untouched. Documented
  as what it actually is: a registration-time hint, not something
  WebAuthn can cryptographically enforce on every later assertion.
- **A second `VitePWA()` instance for POS was tried and rejected** —
  confirmed by reading the plugin's own source
  (`node_modules/vite-plugin-pwa/dist/chunk-*.js`) that
  `virtual:pwa-register` is one fixed global module name with no
  per-instance scoping, so a second instance would race Minions'
  existing one over which wins that import — silently registering the
  *wrong* service worker is worse than a build error. POS instead has a
  hand-written `public/pos-sw.js` + `public/pos-manifest.webmanifest`,
  registered with an explicit `scope: "/pos.html"` so it can never
  collide with the main shell's or Minions'. Verified in the actual
  build output (`dist/pos.html` carries the right manifest link,
  `dist/index.html` carries none, `dist/minions.html` unchanged).
- **⚠️ Not verified — real hardware, not a code question**: whether a
  shared tablet with multiple cashiers each enrolling their own
  fingerprint actually lets WebAuthn's discoverable login pick the
  right one per scan. iOS/Android both support multiple platform
  passkeys per device in principle; this needs a real 10-minute spike on
  actual target hardware before trusting the shared-device model for
  real. If it doesn't hold, the code is unaffected — one enrolled slot
  per device instead of per-person, a rollout concern, not a rewrite.
- No browser-automation tool was connected this session and Docker
  still wouldn't start, so this was verified by `tsc --noEmit`,
  `vite build` (inspected the actual `dist/` output by hand), `go
  build`/`go vet`, and careful manual tracing — **never actually
  exercised in a running browser with a real passkey**. Do that, plus
  the hardware spike above, before trusting this live.
- **Shift open/close has no frontend UI at all**, found while scoping
  this (the backend's always had it) — explicitly out of scope for this
  pass, noted as a separate fast-follow, not silently dropped.

---

## Next up, in order

### 1. Verify everything for real, not just statically — partially done

Attempted at the start of the next session: a real browser test (via
claude-in-chrome) found and fixed a genuine bug — visiting `/pos.html`
directly rewrote the URL to `/` via `PosApp`'s own wildcard route,
harmless until the next reload silently served the main shell instead
of POS. Fixed (`web/src/pos-main.tsx`, adaptive `basename`). Confirmed
clean console, correct routing, and graceful failure with no backend
running. **Minions has the identical latent bug** (same unmodified
`BrowserRouter` pattern, never hit because nobody's tested visiting
`minions.html` directly outside its intended subdomain) — flagged, not
fixed, out of this session's scope.

**Later still — Docker Desktop recovered (user did a factory reset) and
`pytest` finally ran for real.** Worth the wait: it caught two genuine
bugs neither static checking nor manual tracing had surfaced.

- **`payments_method_check` rejected every real Pesapal payment.**
  `0007_pos_identity.sql`/`models.py` added `"pesapal"` to the Python-side
  `PAYMENT_METHODS` tuple but never widened the matching DB-level CHECK
  constraint — `pesapal_webhook`'s own `Payment` insert violated it on
  every confirmed payment. New
  `apps/invoicing/migrations/0008_pesapal_payment_method.sql` (same
  drop+add pattern `0003_pos_returns.sql` already used to add
  `"refund"`). This is exactly the kind of bug that only a real
  migrated database, not syntax/lint checks, can catch — and exactly
  why "verified by tracing" was never a substitute for "verified by
  running."
- **Three new `employee_sales` tests were silently testing nothing.**
  `POST /employees` is `require_role("admin")`-gated; the tests' default
  `principal` fixture is `role="member"`, so every employee-creation
  call 403'd — making every downstream assertion about "does the sale
  get attributed correctly" meaningless (there was never an employee to
  attribute to). Fixed to use the same `_as_admin` helper
  `test_employees.py`/`test_payroll.py` already established.
- **Both suites now fully green for real**: 72/72 `apps/invoicing`,
  31/31 `apps/minions`.

Still unverified, **not a code problem, needs different resources**:
no real WebAuthn register/login ceremony exercised in an actual browser
with a real passkey (claude-in-chrome confirmed the UI renders and fails
gracefully with no backend, but never got a live backend to complete the
ceremony against), no Pesapal sandbox flow confirmed against the real
API, and the shared-device multi-fingerprint hardware spike remains
entirely undone — needs physical device access. Minions' identical
latent routing bug (see above) also still needs its own fix, out of
scope here.

### 2. Close the COGS no-op

`apps/accounting`'s `pos_sale_cogs` webhook has never posted a real
entry — `unit_cost_cents` is documented as always `None` in the event
payload (`invoicing.pos_sale.recorded`'s construction in
`apps/invoicing/app/events.py`), even though `InvoiceLine.unit_cost_cents`
itself is already populated when a POS line is rung up from the product
catalog. Margin/profit reporting is silently wrong today as a result —
revenue posts correctly, cost of goods never does. Likely a small fix
(thread the already-captured value through), confirm scope before
starting.

### 3. Decide the fate of the island apps

`projects`, `fleets`, and `web3` publish nothing, subscribe to nothing,
and nothing else references their data (confirmed by a repo-wide grep
for cross-references) — CRM is one-directional (feeds invoicing, nothing
feeds back). Part of the user's "all these apps depend on each other"
complaint. Needs a product decision, not just code: which of these
should actually integrate with the rest (and how), vs. staying
legitimately independent for now.

### 4. Self-serve data import

There's a one-off dev script
(`scripts/host-data-import-template.py`) but nothing in-product for an
org to bring in an Excel sheet or connect an external DB/spreadsheet for
inventory or CRM data — raised explicitly by the user ("we can't connect
it to excel or database that we do have"). Not scoped yet.

### 5. Minions meeting scheduling — unblocked (Google Calendar OAuth2 done)

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

### 6. Enterprise-grade invoicing/checkout breadth (generic frontend)

Mirrors Friday Host's own `ROADMAP.md` Increment 6 item 2: `crm`,
`fleets`, and `projects` have **no custom frontend at all**, rendering
purely through the generic `web/src/ui/resource/{ListView,KanbanView,
FormView}.tsx` pattern. Not started.

---

## Open decisions / things to confirm before they block something

- Whether Minions meeting scheduling is a new resource or extends the
  cross-app pattern (see #5 above) — resolve as part of its own design
  pass before writing code.
- ~~Whether POS's biometric cashier gate should be constrained to
  platform authenticators~~ — **decided and shipped**: platform-only,
  registration-time only (see the status snapshot above).
- Which of `projects`/`fleets`/`web3` (item #3) should actually
  integrate with the rest of the system — a product decision, not a
  technical one.
- Whether the shared-register-device model for POS clock-in actually
  holds on real hardware (multiple enrolled fingerprints, one device) —
  unverified, see item #1 above.

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
