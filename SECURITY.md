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

- No secrets committed to the repo; all credentials come from environment
  variables (`.env`, never `.env.example`) — see `.gitignore`.
- Every multi-tenant query is scoped by `org_id` and enforced by Postgres
  Row-Level Security, not just application-layer filtering.
- Passwords are hashed with bcrypt; sessions use short-lived JWTs plus a
  rotating refresh token.
- Dependencies are pinned (`go.sum`, `requirements*.lock`, `Cargo.lock`,
  `package-lock.json`) and scanned in CI.
