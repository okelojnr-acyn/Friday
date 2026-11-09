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

---

## Next up, in order

### 1. Google Calendar OAuth2 — genuinely greenfield

Confirmed via a repo-wide grep this session: **zero OAuth2 code exists
anywhere in Friday today.** `friday_common/integrations/google_calendar.py`
is a stub whose own docstring already says this — the adapter is the
*last* piece, not the first. Needed, roughly in build order:

1. A "Connect Google Calendar" UI distinct from every other provider's
   simple paste-a-key form (`IntegrationsSettingsPage.tsx`'s `PROVIDERS`
   entry already lists `client_id`/`client_secret`/`refresh_token` as
   config fields, but nothing drives the OAuth consent redirect that
   actually produces a `refresh_token` today — a user has no way to get
   one).
2. An authorization-redirect endpoint + callback route. Needs a home —
   almost certainly a new route in Friday's Go kernel (`kernel/internal/...`),
   since that's the only piece with a stable public URL today
   (`friday-api.fridayhost.dev`) and already owns `core.integration_credentials`.
3. State/CSRF protection on the redirect (standard OAuth2 concern, not
   Google-specific).
4. Token exchange + refresh-token storage into
   `core.integration_credentials` via the kernel's existing integrations
   endpoints (`kernel/internal/integrations`) — no new storage mechanism
   needed, just a new way to populate it besides "paste into a form."
5. Only then: finish `GoogleCalendarProvider.create_event` for real
   (the actual Calendar API call is the easy part — see `stripe.py` for
   the "plain httpx, no vendor SDK" shape every code-ready adapter uses).

This needs its own design/plan pass before writing code — don't start
mid-session on something this size without one, same rule every other
nontrivial feature in Friday Host's own `ROADMAP.md` follows.

### 2. Minions meeting scheduling — depends on #1

Confirmed this session: Minions has **zero** task/calendar/meeting
concept today — only `employee`, `expense_claim`, `payroll_run`
resources exist (`apps/minions/app/main.py`). `web/src/minions/MyTasksPage.tsx`
is a thin read of **Projects'** `task` resource filtered client-side by
`assignee_email`, not a Minions-owned concept — its own code comment
already flags "a real employee<->task link is a documented follow-on,
not in this pass."

Open design question for the next session to resolve before coding:
does "easy meeting scheduling" become a new Minions-owned resource
(e.g. `meeting`, calling `GoogleCalendarProvider.create_event` on
create), or does it extend the existing cross-app pattern `MyTasksPage`
already uses (read/write into Projects' `task` with a calendar-event
side effect)? Either is viable; neither has been decided yet.

### 3. Enterprise-grade invoicing/checkout breadth

Part of the user's standing "functional as a real CRM" ask. Mirrors
Friday Host's own `ROADMAP.md` Increment 6 item 2 (same gap, the other
side of the fence): `crm`, `fleets`, and `projects` have **no custom
frontend at all** — they render purely through the generic schema-driven
`web/src/ui/resource/{ListView,KanbanView,FormView}.tsx` pattern.
Investing in those generic components has the widest payoff across the
most apps, rather than one-off custom pages per app — `accounting`,
`inventory`, `invoicing`, `web3`, and `pos` already have real custom
frontends and don't need this pass. Not started.

---

## Open decisions / things to confirm before they block something

- Where exactly the Google Calendar OAuth callback route lives (kernel
  vs. a new small Go package) — pick this as part of #1's design pass,
  not ad hoc mid-implementation.
- Whether Minions meeting scheduling is a new resource or extends the
  cross-app pattern (see #2 above) — same, resolve as part of its own
  design pass.

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
