# Friday Architecture

Friday is five pieces talking over HTTP, not a monolith and not a
microservices sprawl. Each piece is boring and small on purpose — see
`DESIGN.md` for the product/UI reasoning, `PRD.md` for the product scope
this architecture serves, and `CONTRIBUTING.md` for the day-to-day
workflow. This document is the "why does it fit together this way"
reference all three point to.

## The five pieces

```
                         ┌────────────────────┐
  Browser  ───────────▶  │  kernel (Go)        │
  (web/)                 │  auth · orgs · apps  │
                         │  catalog · gateway   │
                         │  integration creds   │
                         └─────────┬────────────┘
                                   │ reverse proxy
                                   │ /api/{app}/* → app's BaseURL
          ┌──────────┬──────────┬───────────┬──────────┐
          ▼          ▼          ▼           ▼          ▼
   apps/crm   apps/invoicing  apps/projects  apps/inventory  apps/web3
   (FastAPI)   (FastAPI)       (FastAPI)      (FastAPI)       (FastAPI)
    own schema  own schema      own schema     own schema      own schema
```

- **`kernel/` (Go)** — the only thing the browser ever talks to. Owns
  auth (JWT issuance/verification), the org/membership model, the apps
  catalog (which apps exist in this deployment, which ones an org has
  enabled), the per-org third-party integration credential store
  (`kernel/internal/integrations` — see "Integrations" below), and a
  reverse-proxy gateway that forwards `/api/{app}/*` to the right app
  service with the caller's bearer token passed through unchanged. It
  also fans out domain events between apps
  (`kernel/internal/gateway/events.go`) — see "Cross-app integration"
  below.
- **`apps/*` (Python/FastAPI)** — one business domain per app
  (`crm`, `invoicing`, `projects`, `inventory`, `web3`), each owning its
  own Postgres schema and migration, each verifying the kernel-issued JWT
  itself (shared HS256 secret — see "Trust boundary" below) rather than
  calling back into the kernel per request. Every app is built on
  `packages/py-common/friday_common` (`create_app`, auth dependency,
  DB session, the resource/schema registry, and the integration-adapter
  package — see below) so adding an app never means re-inventing health
  checks, CORS, or the schema endpoint.
- **`pos-engine/` (Rust)** — cart/pricing/tax math and an offline sale
  queue, compiled both natively (`cargo test`, any future backend reuse)
  and to WASM (`wasm-pack build --target web`) for the browser POS
  register in `web/src/apps/pos`. Kept to a small JSON-in/JSON-out
  `wasm_bindgen` surface (`src/wasm.rs`) deliberately — a smaller, more
  stable contract for the TypeScript side than mapping every Rust type
  to a JS class.
- **`web/` (TypeScript/React)** — the one UI every app renders inside.
  Talks only to the kernel (`/auth/*`, `/orgs/apps`, `/api/{app}/*`),
  never to an app service directly.

## The schema-driven UI contract

This is the biggest simplification Friday makes relative to a legacy
ERP's view layer. A legacy system needs an XML view-inheritance system
so modules can patch each other's screens. Friday doesn't have modules
patching each other's screens — it has apps declaring their data shape
once:

```python
resource(ResourceSpec(
    name="opportunity", app="crm", label="Opportunity", ...,
    views=("list", "kanban", "form"), kanban_group_by="stage",
    fields=(FieldSpec("contact_name", "Contact", "text", required=True), ...),
))
```

(`packages/py-common/friday_common/resource.py`). Every app exposes
`GET /schema` (wired in `friday_common/app_factory.py`) returning every
`ResourceSpec` it registered, as JSON. `web/src/ui/resource` turns that
JSON directly into list/kanban/form screens with zero per-resource React
code — CRM's pipeline kanban, Invoicing's customer/invoice lists, and
Projects' task/ticket kanbans are all the *same* generic renderer reading
different schemas. A `FieldSpec` of type `"reference"` (e.g. Task's
`project_id`, Invoice's `customer_id`) is a real relation, not a text
box: it renders as a searchable picker over the target resource
(`ReferenceInput.tsx`), and any resource referencing the one currently
open gets a "smart button" count+link for free, derived by scanning the
app's own schema for a matching `reference` (`SmartButtons.tsx`) -- no
per-resource wiring on either side. An app only gets a hand-written
screen when the workflow genuinely doesn't fit list/kanban/form -- in
this codebase, that's the POS register (`web/src/apps/pos`), because a
cart with live tax/offline-sync math isn't a CRUD form, and Invoicing's
"New Invoice" (`web/src/apps/invoicing/InvoiceCreateModal.tsx`), because
creating an invoice needs a customer and line items up front, not a flat
field list.

## The permission model

Four roles — `viewer < member < admin < owner` — each a strict superset
of the one before (`friday_common/auth.py`'s `ROLE_RANK`). No group/ACL
graph, no per-field record rules. A route either requires no particular
role (any authenticated member of the org) or calls
`Depends(require_role("admin"))`. This is a deliberate ceiling, not a
missing feature: Friday's target is small/mid orgs where "can this
person manage billing" is the only permission question that actually
comes up, not a configurable rules engine.

## Trust boundary

The kernel signs session JWTs with a single shared `JWT_SECRET`
(HS256). Every app verifies with that same secret instead of calling
back into the kernel on every request — this only works because kernel
and apps are one deployment's trust boundary. If apps ever need to live
in separate deployments/trust boundaries, that's the point to swap
HS256 + shared secret for RS256 + a JWKS endpoint; nothing else about
the contract (`Claims{OrgID, Role, Email, sub}` in
`kernel/internal/auth/jwt.go`, mirrored in `friday_common/auth.py`)
would need to change.

## Cross-app integration: events, not direct calls

Apps never import or call each other directly. Two integration points
exist so far, both the same shape: winning an opportunity
(`apps/crm/app/main.py`) publishes a `crm.opportunity.won` event to
`POST /internal/events` on the kernel
(`kernel/internal/gateway/events.go`), which fans it out to subscribing
apps' webhook endpoints (`apps/invoicing/app/webhooks.py`) so Invoicing
can draft an invoice from the won deal; recording a POS sale
(`apps/invoicing/app/main.py`'s `record_pos_sale`) publishes
`invoicing.pos_sale.recorded`, which Inventory subscribes to
(`apps/inventory/app/main.py`'s `pos_sale_recorded`) to decrement stock
for every sold line that carries a `product_id`. This is deliberately
plain HTTP POST, not a message broker — at Friday's target scale, a
broker is infrastructure to operate for a problem ("one app tells
another app something happened") that HTTP already solves, and every
event hop is visible in normal HTTP logs instead of hidden in queue
internals. Adding a new cross-app reaction is one line in
`kernel/internal/gateway/events.go`'s `subscriptions` list plus a
webhook handler in the subscribing app — see either example above.

The POS register reuses the same "already-paid invoice" shape instead of
a separate sales ledger: `POST /api/invoicing/pos/sales` creates an
`Invoice` with `source="pos"` and an immediate `Payment` — one ledger to
reconcile, not two. A line rung up from the product catalog (barcode
scan or search, not freeform entry) carries a `product_id`, set
client-side in `web/src/apps/pos/PosPage.tsx` and threaded through
`pos-engine`'s `LineItem` (`pos-engine/src/cart.rs`) so it survives the
register's offline sync queue — a sale made offline still decrements
stock correctly once it syncs, not just an online one.

## Integrations

A third-party provider (Stripe, Slack, Acyn Wallet, ...) is connected
per-org, not per-deployment: an org admin pastes an API key or webhook
URL into Settings > Integrations, which calls the kernel's
`core.integration_credentials` store (`kernel/internal/integrations`,
migration `0002_integrations.sql`) — one JSON blob per `(org, provider)`.
An app fetches it back with `friday_common.get_integration_config(org_id,
provider)`, a plain HTTP call to the kernel guarded by the same shared
token `events.go` already uses for the reverse direction, returning `{}`
(never raising) if the org hasn't connected that provider.

Every provider is wrapped in a small adapter
(`packages/py-common/friday_common/integrations/*.py`) implementing one
of a handful of category interfaces (`base.py`): `PaymentProvider`,
`ChatProvider`, `CalendarProvider`, `WalletProvider`, `OnChainProvider`,
`CustodyProvider`, `OnOffRampProvider`, `BaaSProvider`. An app's call site
depends on the interface, not the vendor — CRM's won/lost Slack
notification (`apps/crm/app/main.py`'s `_notify_slack`) and Invoicing's
Stripe pay-with-card (`apps/invoicing/app/main.py`'s `pay_with_card`,
`apps/invoicing/app/webhooks.py`'s `stripe_webhook`) are the two
code-ready, real examples; every other listed provider is the same
interface behind a documented stub. See `INTEGRATIONS.md` for the full
provider list, which are code-ready vs. stubs, and the exact config shape
each one expects — that file is also the instruction set a coding agent
follows to finish a stub, so the pattern stays consistent no matter who
(or what) extends it.

One webhook in this system breaks the "kernel is the only public entry
point" rule on purpose: Stripe calls `apps/invoicing/app/webhooks.py`'s
`stripe_webhook` directly, because Stripe can't carry a Friday session
token for the kernel's gateway to check. That route verifies Stripe's own
request signature instead of a bearer token — see its doc comment for
the full trust model — and a production deployment needs to route that
one path to the invoicing service directly, bypassing the kernel.

## Data ownership

Every app's migration lives under its own directory
(`apps/crm/migrations`, etc.) and creates its own Postgres schema. Apps
reference `core.orgs(id)` / `core.users(id)` **by id only** — no foreign
keys across schemas (`kernel/migrations/0001_core.sql`'s header comment
is explicit about this). That's what lets any single app be pulled out
into its own database later without a migration on `core`, and is why
cross-app reads go through each app's own HTTP API (or the event bus),
never a cross-schema SQL join.

## What we explicitly did not build

No XML view-inheritance system, no deep ACL/record-rule graph, no
dual free/paywalled edition, no message broker, no 80-item app menu, no
built-in scheduler (`apps/invoicing/app/main.py`'s
`generate_recurring_invoices` exists to be *called* on a schedule — cron,
Task Scheduler, whatever a deployment already runs — not to run one
itself), no OAuth consent/callback flow in the web shell yet (the one
integration that needs it, Google Calendar, is a documented stub for
exactly that reason — see `INTEGRATIONS.md`). Each of these is a real
feature in systems like Odoo that Friday is intentionally lighter than —
see `DESIGN.md` for the product-level version of this same argument, and
`PRD.md` for why "cheap to extend" matters more here than "comes with
everything built in."
