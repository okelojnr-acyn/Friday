# Security Policy

## Supported Versions

Friday is pre-1.0. Security fixes land on `main` only; there is no LTS branch yet.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting for this repository
(Security tab → "Report a vulnerability"), or email the maintainers listed in
`CONTRIBUTING.md`. Include:

- A description of the issue and its impact
- Steps to reproduce (minimal repro case if possible)
- Affected version/commit

We aim to acknowledge reports within 5 business days.

## Scope

In scope: `kernel/`, `apps/*`, `pos-engine/`, `web/`, and the `infra/` deployment
scripts in this repository. Out of scope: vulnerabilities in third-party
services you choose to deploy Friday on (Supabase, AWS, Vercel, Netlify) —
report those to the respective vendor.

## Baseline practices this project follows

- **No secrets committed to the repo**; all credentials come from
  environment variables (`.env`, never `.env.example`) — see
  `.gitignore`.
- **Passwordless auth** — WebAuthn passkeys plus an emailed one-time
  code as the only fallback, no password field or username anywhere
  (see `ARCHITECTURE.md`'s "Authentication" section). Sessions are a
  single HS256 JWT, 24h TTL, no refresh token (if you need shorter-lived
  access tokens with rotation, that's a deliberate gap to fill, not
  something already half-built here).
- **Rate limiting** on every auth endpoint (`kernel/internal/ratelimit`)
  — a tight per-IP quota on login/signup/OTP routes specifically, a
  looser one across everything else the kernel serves. In-memory and
  per-process by design (see that package's own doc comment for the
  multi-replica caveat) — appropriate at Friday's target scale, not a
  claim that it scales to a large multi-region deployment unmodified.
- **Row-Level Security** on every multi-tenant table in `apps/*`
  (`crm`/`invoicing`/`projects`/`inventory`/`web3`'s own Postgres
  schemas) — every query is scoped by `org_id` in application code
  *and* enforced by a Postgres RLS policy as a backstop, not
  application-layer filtering alone. The kernel's own `core` schema
  (orgs, users, memberships, integration credentials, passkey/OTP
  tables) does **not** use Postgres RLS — the kernel is the one trusted
  service with a single DB role, not a shared role scoped per request
  the way `apps/*` are, so each query is scoped by an explicit `WHERE
  org_id = $1` / `WHERE user_id = $1` instead. See `ARCHITECTURE.md`'s
  "Data ownership" for the full reasoning.
- **Parameterized queries everywhere.** Every query in `kernel/` and
  `apps/*` uses placeholders ($1, SQLAlchemy bound params) for anything
  request-derived; the only string-interpolated SQL in the codebase is
  a schema *name* (`"crm"`, `"invoicing"`, ...), always a deploy-time
  constant from the call site, never from a request.
- **No cookies** — the web shell holds its session token in
  `localStorage` and sends it as an `Authorization: Bearer` header, not
  a cookie. This is a deliberate CSRF mitigation: a browser only
  auto-attaches cookies to a cross-site request, not an explicit header,
  so the classic CSRF attack shape doesn't apply here the way it would
  to a cookie-session app.
- **Basic response hardening** (`X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`) and a request
  body size cap on everything the kernel serves directly.
- **Dependency hygiene**: Go (`go.sum`) and JS (`package-lock.json`) and
  Rust (`Cargo.lock`) dependencies are lockfile-pinned; Python
  dependencies currently use loose `>=` specifiers in
  `requirements*.txt` (not hash-pinned -- a real gap if you need fully
  reproducible Python builds). `.github/dependabot.yml` opens weekly
  update PRs across all four ecosystems, and GitHub's own dependency
  graph flags known-vulnerable versions on this repo.
