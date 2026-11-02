# Contributing to Friday

Friday is a small set of focused business apps on a shared kernel. The bar
for a change: does it make the product simpler to use, or does it add a knob
nobody asked for? We'd rather ship fewer, sharper features than grow a menu
tree nobody can navigate.

## Project layout

See `ARCHITECTURE.md` for the full picture. Short version:

- `kernel/` (Go) — auth, orgs, roles, the app registry, the API gateway.
- `apps/*` (Python/FastAPI) — one business domain per app, each owns its own
  Postgres schema and talks to the rest of the system only through the
  kernel's event bus and its own HTTP API.
- `pos-engine/` (Rust) — compiled to a native binary and to WASM so the same
  cart/pricing/tax/offline-sync logic runs identically in the browser POS
  screen and anywhere else that needs it.
- `web/` (TypeScript/React) — the unified shell every app renders inside.
- `infra/` — everything needed to run Friday: Docker Compose locally,
  Supabase/AWS/Vercel/Netlify scripts for hosted deployments.

## Adding a new app

Don't hand-roll the boilerplate. Run:

```
./scripts/new-app.sh my_app
```

This scaffolds a FastAPI service with the standard shape (models, a JSON
schema the generic UI renders automatically, a migration, and a registry
entry), so the new app is navigable from day one without any bespoke
frontend work. Only write custom screens for workflows that genuinely need
one (a kanban board, the POS register) — everything else should render from
the schema.

## Development setup

```
./scripts/setup.sh      # bootstraps .env, migrates, seeds demo data
docker compose -f infra/docker-compose.yml up
```

See `README.md` for the full quickstart and per-language dev commands.

## Before opening a PR

- Run the relevant toolchain's real build/test command (`go build ./... && go vet ./...`,
  `pytest`, `cargo test`, `tsc --noEmit && npm run build`) — CI runs the same
  checks and will fail the same way.
- Keep changes scoped to one app/package where possible; cross-app changes
  should go through the kernel's event bus, not direct imports.
- If you're adding a UI screen, use the shared `web/src/ui` component kit
  instead of one-off styling — this is what keeps the product visually
  consistent as it grows.

## Reporting bugs / security issues

Bugs: open a GitHub issue with repro steps.
Security vulnerabilities: see `SECURITY.md` — do not open a public issue.

## License

By contributing, you agree your contributions are licensed under the
project's MIT license (`LICENSE`).
