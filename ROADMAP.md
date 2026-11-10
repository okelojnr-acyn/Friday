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

**Read `friday-cloud-labs/ROADMAP.md`'s "NEXT SESSION — START HERE"
section (top of that file, added 2026-11-10) before this one** if
you're picking up fresh — it's the cross-repo handoff covering both
products together (critical bugs ranked by what blocks a real paying
customer, what's stale, the actual path to launch). This file has the
Friday-specific detail underneath it.

**Update 2026-11-10 ~13:30 UTC — incident, read first**: all 9 live
containers were updated to `e16ac1be` at ~02:22 UTC (so "the live
kernel is behind" below is **stale** — passkey logging etc. is live).
That update took every app down: Friday Host's update path dropped the
apps' network aliases and moved the kernel onto gVisor, so the gateway
couldn't resolve any app. Not a bug in this repo. Full write-up, the
code fix, and the repair runbook are in `friday-cloud-labs/ROADMAP.md`
→ "Incident 2026-11-10". **Friday-side follow-up it created**: every
app needs a real `GET /health` (today they 404 on it) so Friday Host's
planned blue/green update (its Increment 6.5) can health-check before
swapping.

---

## Status snapshot — 2026-11-09

**Deployed as of 2026-11-09**: kernel + crm + invoicing run as real
tenant containers on Friday Host, web shell live at
`https://friday.fridayhost.dev`.

**Update, 2026-11-10 — superseded, kept for history**: the paragraph
above was accurate when written but is wrong now. The other six apps
(projects, inventory, web3, accounting, minions, fleets) are deployed
too as of 2026-11-10 (`friday-cloud-labs/ROADMAP.md`'s own session note
has the full detail: `fridayBuildSpecs` was missing them, not a
decision to leave them undeployed). **The live kernel is still on an
older commit than `main`, though** — see this file's very top ("NEXT
SESSION — START HERE" pointer) before assuming anything deployed today
is actually live.

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

### 1. Verify everything for real, not just statically — done, as far as software alone can take it

Attempted at the start of the next session: a real browser test (via
claude-in-chrome) found and fixed a genuine bug — visiting `/pos.html`
directly rewrote the URL to `/` via `PosApp`'s own wildcard route,
harmless until the next reload silently served the main shell instead
of POS. Fixed (`web/src/pos-main.tsx`, adaptive `basename`). Confirmed
clean console, correct routing, and graceful failure with no backend
running. **Minions had the identical latent bug** (same unmodified
`BrowserRouter` pattern, never hit because nobody's tested visiting
`minions.html` directly outside its intended subdomain) — flagged this
session, fixed next (`web/src/minions-main.tsx`, same adaptive
`basename`), confirmed in a real browser: stays at `/minions.html`, no
redirect.

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

**Later still — the real WebAuthn ceremony test, with the full stack
actually running together for the first time.** Postgres (Docker,
trust-auth container), the kernel, and the web dev server were all
brought up together and exercised for real via claude-in-chrome:

- **Real signup end to end**: created a real org, the kernel logged a
  genuine OTP to its own stdout (no SMTP configured), entered it, got a
  real session. Confirms the entire kernel auth stack (JWT issuance,
  org creation, OTP flow, CORS, frontend-kernel wiring) works for real,
  not just in tests.
- **The WebAuthn ceremony itself genuinely can't be completed from
  here** — confirmed, not assumed. Clicking "Set up a passkey" correctly
  called `register-options`, got a real challenge back from the kernel,
  and invoked the browser's real `navigator.credentials.create()` — it
  didn't hang or error out before that point. It resolved a few seconds
  later to "Could not set up a passkey": this automated Chrome
  environment has no platform authenticator available, so the ceremony
  fails cleanly without ever reaching a biometric prompt. This is as far
  as software alone can verify the chain; completing a real
  registration (and the shared-device multi-fingerprint question) needs
  an actual device with a real sensor.
- **The dashboard and the POS clock-in gate both confirmed working for
  real** against the live backend: all 8 apps render, the "Point of
  Sale" tile correctly does a real cross-document navigation to
  `/pos.html` (not a broken SPA route), POS correctly shares the main
  shell's session (no separate login needed) while still demanding a
  fresh clock-in scan on that page load — exactly the designed
  behavior. The `pos-main.tsx` basename fix held too: no reversion to
  the redirect-to-"/" bug.

### ~~2. Close the COGS no-op~~ — not actually broken, corrected 2026-11-09

This was wrong, carried forward from an earlier audit that conflated
two different functions. `apps/invoicing/app/events.py`'s
`invoice_lines_payload` does hardcode `unit_cost_cents: None` — but
that function feeds `invoicing.invoice.paid`, which accounting's
`invoice_paid` handler never reads `.lines`/`unit_cost_cents` from at
all (it only posts Cash/Revenue/Tax from top-level amounts). The
function that actually feeds the COGS webhook
(`publish_pos_sale_recorded`, same file) has always threaded the real
value through from committed `InvoiceLine` rows — and `pos-engine`'s
own `LineItem.unit_cost_cents` (`pos-engine/src/cart.rs`) was
purpose-built for exactly this, carrying it from the product catalog
through the whole chain to the event. Confirmed with a real test run
this session, not just by reading the code: all 13 of
`apps/accounting/tests/test_webhooks.py`'s tests pass against a live
DB, including `test_pos_sale_cogs_posts_for_lines_with_a_known_cost`,
the return-reversal case, and idempotency. If margin reporting looks
wrong in practice, the actual cause is almost certainly that an org
hasn't set a real `cost_cents` on its products (defaults to 0, so
there's genuinely no cost to post) — not a code gap.

### ~~3. Decide the fate of the island apps~~ — Projects linked in, 2026-11-09

Resolved via a real code survey, not a guess: the frontend's reference
system (`ListView`/`ReferenceInput`/`SmartButtons`) already generically
parses `field.reference` as `"app.resource"` and fetches cross-app —
nobody had ever actually pointed one at a different app, so this was
cheap to close, not a missing-architecture problem. Shipped:
`projects.project.opportunity_id -> crm.opportunity` (a won deal becomes
a project) and `projects.ticket.customer_id -> invoicing.customer` (a
helpdesk ticket tied to the real paying customer), both by-id-only, no
FK across schemas. Also fixed a real latent bug this surfaced:
`SmartButtons.tsx`'s reverse-lookup ("what points back at this record")
only ever searched the *current* app's own schema array, so the reverse
direction (a Customer's "Tickets" button) would never have appeared even
though the forward direction worked — now searches every installed
app's schema.

Fleets stays deliberately unlinked for now (`Vehicle.assigned_driver_name`/
`Driver` free-text, by the code's own prior reasoning) — the real gap
there is financial, not referential: `MaintenanceLog`/`FuelLog.cost_cents`
never post anywhere, but neither does Invoicing's revenue (no app posts
to Accounting's ledger automatically yet, anywhere) — that's a real
feature (GL account defaults, debit/credit rules), not a reference field,
and deliberately not bundled into this pass. Worth its own session.

### ~~4. Self-serve data import~~ — shipped, 2026-11-09

`ImportCsvPanel` (`web/src/ui/resource/ImportCsvPanel.tsx`), wired into
`ResourcePage.tsx` for every app/resource at once, not just the two
`host-data-import-template.py` happened to hardcode (inventory products,
invoicing customers). Paste/upload CSV, map columns to the resource's
own schema-driven fields (reuses `FormView`'s `initialValues`/
`toWireBody` so coercion matches the manual form exactly), import row by
row via the same generic create endpoint "New" already uses — zero new
backend routes. Partial-success by design: one bad row doesn't abort the
batch, it shows up in a per-row result list. "Download a template"
button gives the exact column headers a resource expects.

### ~~5. Minions meeting scheduling~~ — shipped, 2026-11-09

Resolved the open design question in favor of a **new resource**
(`minions.meeting`), not extending `MyTasksPage`'s cross-app Task
pattern: a Task is one due date + one assignee shaped for kanban
work-tracking, a meeting is a time *range* with potentially several
attendees, different enough shapes that forcing one into the other would
warp Task for every other caller.

`title`/`starts_at`/`ends_at`/`attendee_emails`, synced to the org's
connected calendar on create and on any calendar-relevant edit
(title/time/attendees — an unrelated field edit doesn't trigger a
pointless resync). `sync_status`/`sync_error` stay visible on the record
rather than failing the request — an org with no Google Calendar
connected can still schedule a meeting, it just stays `'pending'` with a
clear reason. Added the missing `update_event`/`delete_event` to
`CalendarProvider`'s interface (`GoogleCalendarProvider` implements both
for real; the Calendly stub gets matching `NotImplementedError`s) —
deleting a meeting cancels its real calendar event instead of leaving a
stale invite on every attendee's calendar. 7 new tests, all passing in
CI against a real Postgres (caught a real bug before it shipped: the new
table was initially missing `ENABLE`/`FORCE ROW LEVEL SECURITY`
entirely, unlike every other table in this app).

**Still genuinely unverified**: a real Google Cloud OAuth client. See
"Google Calendar — ready for a real test" below for exactly what's left
and how to close it — as of today that gap is entirely on the human side
(Google Cloud Console steps), not code; `KERNEL_PUBLIC_URL` was also
missing in production until today (redirect_uri would have silently
pointed at `localhost`), now fixed.

### 6. Enterprise-grade invoicing/checkout breadth (generic frontend) — CRM started, 2026-11-09

Mirrors Friday Host's own `ROADMAP.md` Increment 6 item 2. **CRM done**:
`web/src/apps/crm/PipelinePage.tsx`, same justification as Accounting's
`ReportsPage`/Web3's `TreasuryPage` — win rate (gauge), open pipeline
value, average deal size, and a lost-reason breakdown are aggregation
reads the generic renderer has no concept of, not CRUD. Reuses the
*actual* `KanbanView` as-is (same drag-and-drop every kanban-enabled
resource already gets), doesn't reinvent it. `/crm` now lands here
instead of the generic list; `/crm/opportunity` and `/crm/activity`
still reach the raw schema-driven screens. Verified in a real browser
(clean console, correct route, graceful no-backend error state) — not
yet verified with a live backend rendering real data.

**`fleets` and `projects` still have no custom frontend** — not started.
Fleets' natural custom view is an operational dashboard (vehicle status
grid, maintenance/fuel cost rollups per vehicle); Projects' marginal
gain is smaller since Task already gets a kanban view free from the
generic renderer.

---

## Open decisions / things to confirm before they block something

- ~~Whether Minions meeting scheduling is a new resource or extends the
  cross-app pattern~~ — **decided and shipped, 2026-11-09**: new
  resource (`minions.meeting`), see item #5 above for why.
- ~~Whether POS's biometric cashier gate should be constrained to
  platform authenticators~~ — **decided and shipped**: platform-only,
  registration-time only (see the status snapshot above).
- ~~Which of `projects`/`fleets`/`web3` should actually integrate with
  the rest of the system~~ — **decided and shipped, 2026-11-09**:
  Projects linked to CRM/Invoicing now; Fleets/Web3 stay independent for
  now (financial auto-posting is the real gap, not a reference field —
  see item #3 above).
- **Pushed to next session, on purpose (2026-11-09)**: whether the
  shared-register-device model for POS clock-in actually holds on real
  hardware (multiple enrolled fingerprints, one device). See the
  dedicated "WebAuthn shared-device multi-fingerprint — technical
  handoff" section below for the full state of this: what's confirmed,
  what isn't, exactly how to test it, and every relevant code pointer.
  Needs physical biometric hardware this session didn't have.

## Google Calendar — ready for a real test (2026-11-09)

Code side is done and was re-verified today, not just assumed:
`GoogleCalendarProvider` (`packages/py-common/friday_common/integrations/
google_calendar.py`) implements `create_event`/`update_event`/
`delete_event` for real against Google's REST API; Minions' `meeting`
resource (item #5 above) calls all three; the OAuth consent/callback
flow (`kernel/internal/integrations/google_oauth.go`) and its frontend
(`web/src/shell/IntegrationsSettingsPage.tsx`, Settings → Integrations →
Google Calendar) both already exist and were confirmed present, not
assumed.

**Found and fixed today**: the live kernel (`friday-kernel`, Friday
Host-managed) had no `KERNEL_PUBLIC_URL` set at all, so
`googleRedirectURI()` was silently computing `http://localhost:8080/...`
— unreachable from Google's side, would have failed the consent flow at
the very last step with no useful error. Fixed by recreating the live
container with `KERNEL_PUBLIC_URL=https://friday-api.fridayhost.dev`
added (direct docker surgery, not through Friday Host's own update
path, since there's no API for adding one env var to a running tenant
server — also updated `core.servers.container_id` in Friday Host's own
Postgres afterward so its UI keeps tracking the right container).
**Caused a brief real outage doing this**: the first recreate attempt
removed the old container before the replacement started, failed on an
unrelated shell bug (an empty line from `docker inspect`'s env dump
produced an invalid empty `-e` arg), and the kernel was down for a few
minutes until restored with the same config captured just before the
failed attempt. Lesson for next time: never `docker rm` the old
container before the replacement is confirmed healthy — stop, verify
the new one works, *then* remove the old one, not stop+rm+run as one
uninterruptible block.

What's left is entirely on the human side now: a real Google Cloud
project, OAuth consent screen, and OAuth client with that exact redirect
URI registered, using `acyncupbase@gmail.com`. See the session's own
chat log for the full numbered walkthrough if it's not repeated
elsewhere by the time this is picked back up — the short version is
Cloud Console → enable Calendar API → OAuth consent screen (Testing mode
is fine) → Credentials → OAuth client ID (Web application) → that
redirect URI → paste client ID/secret into Settings → Integrations →
Connect with Google → schedule a test Meeting → check it actually
appears on the real calendar → edit it → delete it, confirming all
three provider methods for real, not just in CI's mocked tests.

## WebAuthn shared-device multi-fingerprint — technical handoff (2026-11-09)

**The question**: POS runs as a shared register device (not
one-per-cashier) — `web/src/apps/pos/PosClockIn.tsx` gates the register
behind a passkey scan, and the *same physical device* is meant to have
multiple cashiers each enroll their own platform fingerprint, so a scan
identifies *whoever's standing there right now* via WebAuthn's
discoverable/usernameless login (`navigator.credentials.get()` with no
`allowCredentials` list, resolving the account from the credential's own
`userHandle`). Does this actually work in practice on real target
hardware — does the OS's native passkey picker correctly disambiguate
between several enrolled fingerprints on one device and let each person
pick (or auto-select) *their own* credential, not just whichever was
enrolled first or most recently? This is a platform/OS behavior
question, not something inspectable in source code.

**Why it still isn't verified, concretely**: completing a real WebAuthn
ceremony requires an actual platform authenticator (Touch ID, Windows
Hello, Android/iOS biometric) — there is no software way to drive one.
This was confirmed empirically this session's predecessor, not assumed:
with the full stack running live (Postgres, kernel, web dev server) and
driven through a real Chrome browser via claude-in-chrome, clicking
"Set up a passkey" correctly reached `navigator.credentials.create()`
and got a real challenge from the kernel — it failed cleanly at
`"Could not set up a passkey"` only because that automated Chrome
environment has no platform authenticator attached, never reaching an
actual biometric prompt. That's the literal ceiling of what this kind
of session can verify alone, confirmed rather than inferred.

**What's already fixed and should make the real test more likely to
pass cleanly** (2026-11-09, this session): both
`kernel/internal/auth/handlers.go`'s `PasskeyRegisterOptions` branches
(the general one and the `?purpose=pos` one) were asking for
`protocol.ResidentKeyRequirementPreferred` instead of `Required`.
`Preferred` lets the authenticator/OS create a *non-discoverable*
credential anyway (a real behavior on several platform authenticators,
not a hypothetical) — but login
(`PasskeyLoginOptions`/`PasskeyLoginVerify`, via
`h.WebAuthn.BeginDiscoverableLogin()`) can only ever see a *resident*
credential. So a passkey could register successfully and then simply
never be usable to log in, with nothing at registration time to explain
why — this is almost certainly why an earlier live attempt to register
and then use a passkey failed on both Friday Host (`friday-cloud-labs`
has the identical bug, also fixed today) and here. Changed both to
`Required`; the POS branch additionally needed
`RequireResidentKey: protocol.ResidentKeyRequired()` set explicitly
since it builds `AuthenticatorSelection` directly rather than through
the `WithResidentKeyRequirement` helper that sets both fields together
(confirmed by reading `go-webauthn`'s actual source,
`webauthn/registration_opt.go`, not guessed).

**Important implication for the hardware test**: any passkey registered
*before* today's fix is almost certainly still broken — the fix only
changes what new registrations ask for, it can't retroactively fix an
already-non-resident credential sitting in `core.webauthn_credentials`.
**Register fresh for the hardware test; don't reuse an old enrollment.**

**Exact test plan for next session** (needs real hardware — a phone or
laptop with a working fingerprint/Face ID sensor, ideally the actual
target POS tablet):

1. Register cashier A's fingerprint via POS's "New cashier? Set up your
   fingerprint" flow (`PosClockIn.tsx`'s `addPasskey({ platformOnly:
   true })`, which now asks for `Required` + `platform` attachment).
   Confirm A can clock out and back in with just a scan.
2. On the *same device*, register cashier B's fingerprint the same way
   (different email, different admin-invited account — see this
   session's POS admin-gating work,
   `kernel/internal/auth/invites.go`'s `PosRequestCode`/`PosVerifyCode`,
   for why B must already be admin-invited first).
3. With both enrolled, scan as A. Confirm the session that comes back is
   actually A's (`session.email` shown in the POS header), not B's or
   whichever was enrolled first.
4. Scan as B. Confirm the same, the other direction.
5. Repeat 3–4 a few times in different orders — the real risk is the OS
   picker defaulting to "most recently used" or "first enrolled" instead
   of correctly disambiguating by which finger/face was actually
   presented.
6. If it fails — the OS can't disambiguate multiple resident credentials
   for the same RP on one device by biometric alone, only by showing an
   account-picker UI first — **the code is unaffected**, per the
   existing design-fork note above: fall back to one enrolled slot per
   device (one shared fingerprint logs in whoever currently owns it,
   explicit hand-off) instead of per-person, a rollout/process change,
   not a rewrite. Document whichever outcome here when it's run.

**Relevant code, all already built, none of it the open question**:
`web/src/lib/auth.tsx` (`loginWithPasskey`/`addPasskey`),
`web/src/apps/pos/PosClockIn.tsx`, `kernel/internal/auth/webauthn.go`
(`storeWebauthnChallenge`/`consumeWebauthnChallenge`/
`loadWebauthnUser`), `kernel/internal/auth/handlers.go`
(`PasskeyRegisterOptions`/`PasskeyRegisterVerify`/
`PasskeyLoginOptions`/`PasskeyLoginVerify`).

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
