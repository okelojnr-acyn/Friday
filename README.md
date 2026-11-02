# Friday

A small, focused business suite — CRM, Invoicing, Projects & Helpdesk,
Inventory, a POS register with barcode scanning, and a Web3 business
wallet — on a shared kernel, with a documented pattern for connecting
third-party tools (Stripe, Slack, Calendly, and more). See `PRD.md` for
the product scope, `DESIGN.md` for the product philosophy,
`ARCHITECTURE.md` for how the pieces fit together, `INTEGRATIONS.md` for
connecting (or finishing) a third-party provider, and
`docs/building-an-industry-site.md` for forking Friday toward one
specific business or industry.

## Quickstart

```
./scripts/setup.sh                            # installs deps for every toolchain, copies .env.example -> .env
docker compose -f infra/docker-compose.yml up  # postgres + kernel + crm + invoicing + projects + inventory + web
```

Then open http://localhost:5173, register an org, and you're in.

Running everything through Docker Compose is the fastest way to a
working stack; each service also runs standalone for focused
development (below).

## Project layout

- `kernel/` (Go) — auth, orgs, the app registry, the API gateway, and the
  per-org third-party integration credential store. Every request from
  `web/` goes through here.
- `apps/*` (Python/FastAPI) — one business domain per app (`crm`,
  `invoicing`, `projects`, `inventory`, `web3`), each with its own
  Postgres schema.
- `pos-engine/` (Rust) — cart/pricing/tax/offline-sync logic, compiled
  native and to WASM for the browser POS register.
- `web/` (TypeScript/React) — the unified shell every app renders
  inside, plus the generic schema-driven list/kanban/form renderer.
- `infra/` — Docker Compose for local dev; `infra/aws`,
  `infra/supabase`, `infra/vercel-netlify` for hosted deployments.

## Per-language dev commands

Run these from the repo root unless noted.

**Kernel (Go)**
```
cd kernel
go build ./... && go vet ./...
go run ./cmd/kernel
```

**An app (Python/FastAPI)** — same shape for `apps/crm`, `apps/invoicing`,
`apps/projects`, `apps/inventory`, `apps/web3`:
```
cd apps/crm
pip install -r requirements.txt -r requirements-dev.txt
pytest
uvicorn app.main:app --reload --port 8001   # 8002 invoicing, 8003 projects, 8004 inventory, 8005 web3
```

**POS engine (Rust)**
```
cd pos-engine
cargo test
wasm-pack build --target web --out-dir ../web/src/apps/pos/engine --out-name friday_pos_engine
# outputs into web/src/apps/pos/engine (gitignored), imported by web/src/apps/pos/PosPage.tsx
```

**Web (TypeScript/React)**
```
cd web
npm install
npm run dev        # http://localhost:5173
tsc --noEmit && npm run build
```

## Adding a new app

```
./scripts/new-app.sh my_app
```

Scaffolds a FastAPI service in the standard shape (models, a
`ResourceSpec` schema the generic UI renders automatically, a migration,
and a registry entry) — see `CONTRIBUTING.md`.

## Contributing

See `CONTRIBUTING.md` for the full workflow, `SECURITY.md` to report a
vulnerability, and `CODE_OF_CONDUCT.md` for community expectations.

## License

MIT — see `LICENSE`.
