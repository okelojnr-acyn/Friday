# Building an industry site on Friday

Friday is a generic small-business suite (CRM, Invoicing, Projects &
Helpdesk, Inventory, POS, Web3) on a shared kernel -- see `ARCHITECTURE.md`
for how the pieces fit together and `DESIGN.md` for the visual language.
This doc is about the other direction: forking Friday to build something
for one specific business or industry, and which parts of the system are
meant to be touched to do that.

## Three kinds of change, in order of how much code they need

### 1. Configure (no code)

- **Which apps an org sees**: the Apps Catalog (`/apps`) installs/
  uninstalls per org already -- a retail business enables Inventory +
  POS and skips Projects & Helpdesk; a consultancy does the opposite.
  Nothing to build, this already works per-org out of the box.
- **Which integrations are connected**: Settings > Integrations -- see
  `INTEGRATIONS.md`. A salon business might only ever connect Stripe and
  Calendly; a retailer connects Stripe and nothing Web3-shaped.

### 2. Retheme (CSS, no logic)

Every app renders through `web/src/ui` -- no app ships its own buttons,
cards, or inputs (`DESIGN.md`'s "one component kit, every app"). Retheming
for a brand means editing `web/src/ui/tokens.css`'s values, not touching
any app's code:

- `--accent` / `--accent-contrast` -- the one brand color.
- `--bg` / `--surface` -- base and card colors (keep the warm-light vs.
  dark-contrast-band structure in `DESIGN.md` unless the brand genuinely
  wants a different visual language, not just different colors).
- `--font` / `--font-display` -- swap in a brand typeface.
- `kernel/internal/registry/registry.go`'s `Label`/`Description` per app
  -- rename "CRM & Sales" to whatever your industry calls it (a salon
  might call Projects "Bookings," a repair shop might call it "Work
  Orders") without changing any of the underlying resource logic.

### 3. Extend (new code)

Three shapes of new code, cheapest to most involved:

- **A field or two on an existing resource**: add a `FieldSpec` to a
  `ResourceSpec` in that app's `main.py`, a column via a new migration
  file, and a matching field on the Pydantic schema. A tattoo studio
  adding "consent form signed" to a CRM contact is this shape. No web
  code needed -- the generic list/kanban/form renderer picks it up.
- **A new resource in an existing app**: same as above plus a new
  SQLAlchemy model and a list/create (and maybe update/delete) router --
  `apps/crm/app/main.py`'s `Activity` resource (added for the note/
  timeline feature) or `apps/inventory/app/main.py`'s `Supplier`/
  `PurchaseOrder` pair are the templates to copy.
- **A whole new app**: `./scripts/new-app.sh my_app` scaffolds a FastAPI
  service in the standard shape (see `CONTRIBUTING.md`), then add it to
  `kernel/internal/registry/registry.go` and `infra/docker-compose.yml`
  (see `apps/web3`'s addition as the most recent worked example of every
  file that touches). A property-management fork might add a `leases`
  app this way instead of bending Invoicing to fit.

A hand-written React screen (not the generic list/kanban/form renderer) is
only worth it when the workflow genuinely isn't a flat field list -- the
POS register, Invoicing's "New Invoice," Invoicing's "Pay with card"
panel, Inventory's "Create purchase order" panel, and Web3's Treasury
panel are the existing examples, each with a doc comment explaining why
it earned one. Reach for the generic renderer first.

## What's meant to stay a scaffold

Some of what's in this repo is intentionally unfinished, for a fork to
complete only if it actually needs that piece:

- Every **stub** integration adapter in `INTEGRATIONS.md` (Calendly,
  Google Calendar, Paystack, Pesapal, Atlas, Bridge, Alchemy, Turnkey) --
  a real interface and a docstring, no real HTTP calls yet. Finish the
  ones your business actually uses; leave the rest.
- The direct Alchemy/Turnkey/Bridge path for Web3 custody, as opposed to
  going through Acyn Wallet -- only worth building if you specifically
  need your own custody stack instead of a managed one.
- `apps/invoicing/app/main.py`'s `generate_recurring_invoices` has no
  built-in scheduler calling it (Friday deliberately has none -- see
  `ARCHITECTURE.md`'s "what we explicitly did not build"). A deployment
  that sells subscriptions wires a cron job or Task Scheduler entry to
  call it; one that doesn't, never needs to.
- A full per-record activity/comment trail (Odoo's "chatter") beyond
  CRM's `Activity` resource -- `DESIGN.md` calls this out explicitly as a
  real gap, not a simplification to claim credit for. Build it the same
  shape as `Activity` (a resource with a `reference` field back to its
  parent) if your industry genuinely needs it on every resource, not
  just Opportunities.

## Picking an industry's starting app set

A few worked examples, as a sense of what to enable/retheme/extend and
what to leave alone:

| Business | Enable | Retheme | Extend |
|---|---|---|---|
| Retail shop | Inventory, POS, Invoicing | Brand colors, "Shop" labels | Barcode-driven reorder thresholds already exist; maybe a loyalty-points field on Customer |
| Service business (salon, repair) | CRM, Projects & Helpdesk, Invoicing | Rename "Projects" to "Bookings"/"Work Orders" | Calendly integration (finish the stub) for booking links |
| B2B SaaS / consultancy | CRM, Invoicing, Projects & Helpdesk | Minimal -- defaults suit this best | Stripe recurring billing (already code-ready), a `Contract` resource |
| Fintech / payments-adjacent | Invoicing, Web3 | Compliance-forward copy | Finish the Web3 app's direct-custody path if Acyn Wallet's model doesn't fit |

None of this requires forking the kernel, the design system, or the
schema-driven UI contract -- that's the point of the architecture in
`ARCHITECTURE.md`: the parts that make Friday "Friday" stay fixed, and an
industry fork is additive configuration, theming, and resources on top.

This table is also what `INSTALL.md`'s Step 2 points at when installing
Friday as the admin layer of an *existing* site, not just a fresh fork --
same question either way: what does this business actually do, and
which apps earn a place because of it.

## Before this goes live for real customers

Two things this doc intentionally doesn't cover, because they're
specific to each deployment rather than generic to "building an
industry site":

- **Legal documents** -- `legal/` has Privacy Policy, Terms of Service,
  and Cookie Policy templates. They are templates, not finished
  documents; read `legal/README.md` before using any of them.
- **Security configuration specific to this deployment** --
  `SECURITY.md` covers what Friday does by default; `INSTALL.md`'s
  Step 7 covers the handful of things that are this deployment's own
  decision (real secrets, proxy trust, cookie disclosure if you added
  any).
