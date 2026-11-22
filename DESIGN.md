# Friday Design System

Friday's interaction patterns are deliberately unoriginal: an app-launcher
home screen, a consistent top bar, list/kanban/form views with a view
switcher, smart action buttons and an activity log on records, and an "apps"
catalog to enable features per workspace. These patterns are proven at scale
in business software — there is no reason to reinvent navigation just to look
different. What Friday owns is the visual language layered on top of them.

## Principles

1. **Warm and light, not another dark SaaS default.** The base surface is a
   soft off-white (`#f1efe8`), cards are white, elevated with a soft shadow
   instead of a hard border. One near-black "ink" palette exists alongside
   it — not a dark theme toggle, but the deliberate contrast band a
   data-dense section (an activity feed, a chart) sits on. See `.band-ink`
   below.
2. **One accent, used sparingly.** A single warm amber/orange carries all
   primary actions, the gauge fill, and status. Everything else is
   white / ink / warm gray. Color is information, not decoration.
3. **Soft elevation over hard lines.** Cards, kanban cards, modals, and
   smart buttons lift off the page with `--shadow-card` and a large
   `--radius` (22px) rather than a visible border — a stack of real,
   touchable surfaces, not a flat sheet of boxes.
4. **One featured gradient, used once per screen at most.** A single warm
   mesh gradient (`--gradient-ambient`) glows behind a hero metric, and one
   "featured" stat card per screen can carry `--gradient-card`. Everything
   else stays flat — a gradient on every card would stop meaning anything.
5. **Density where it matters, air where it doesn't.** Data tables and
   kanban cards are information-dense (this is work software); surrounding
   chrome (nav, headers, empty states) is generous and calm.
6. **One component kit, every app.** Every app renders through
   `web/src/ui` — no app ships its own buttons, inputs, or cards. This is
   what keeps 5+ independently-built apps feeling like one product, and
   what lets the whole UI restyle from one place. Icons follow the same
   rule: `web/src/ui/Icon.tsx` is one small hand-rolled stroke-icon set
   (`currentColor`, no external icon library), grown by adding a glyph
   there as each new surface needs one (Web3's wallet icon, the
   Integrations settings screen's provider icons) rather than any app
   reaching for its own icon set.

## Tokens (`web/src/ui/tokens.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#f1efe8` | App background (warm off-white) |
| `--surface` | `#ffffff` | Cards, panels, table rows |
| `--surface-raised` | `#ffffff` | Modals, popovers, dropdowns |
| `--border` | `rgba(10,10,8,.08)` | Hairlines, used sparingly — elevation does most of the separating |
| `--text` | `#0e0e0b` | Primary text |
| `--text-muted` | `#87867c` | Secondary text, labels |
| `--accent` | `#e07a35` | Primary actions, gauge fill, active states, links |
| `--accent-contrast` | `#ffffff` | Text/icon color on top of `--accent` |
| `--success` | `#2f9e63` | Won/paid/synced states |
| `--danger` | `#d6483f` | Destructive actions, failed sync, low-stock dots |
| `--radius` | `22px` | Cards, modals, the launcher grid |
| `--radius-sm` | `14px` | Buttons, inputs, kanban cards, dropdowns |
| `--radius-pill` | `999px` | Segmented nav, filter pills, badges |
| `--shadow-card` | soft, ~16px blur | Resting elevation for every card-like surface |
| `--shadow-float` | soft, ~24px blur | Modals, open dropdowns, hover lift |
| `--font` | `Inter, system-ui, sans-serif` | Body text, form labels |
| `--font-display` | `Figtree, Inter, system-ui, sans-serif` | Page titles, stat values, the gauge's big number |
| `--ink-bg` / `--ink-surface` / `--ink-text` / ... | near-black | The `.band-ink` contrast-band palette (see below) |
| `--gradient-ambient` | warm radial mesh | Glow behind the dashboard's hero gauge |
| `--gradient-card` | warm diagonal | One featured `StatCard` per screen, at most |

### The dark contrast band (`.band-ink`)

`.band-ink` re-points `--surface`/`--border`/`--text`/`--text-muted` to the
near-black "ink" palette and nothing else — so any existing component
(buttons, badges, field labels) dropped inside it re-themes automatically,
with zero dark-mode variant to hand-build per component. Used for the
dashboard's "Recent activity" section today; reach for it anywhere a
section genuinely wants to read as a distinct, denser zone (a chart, a
history log) — not as a general dark-mode toggle for the whole app.

## Patterns reused deliberately (proven, not reinvented)

- **Home is the launcher; My Store is the overview** (owner, 2026-11-22)
  — logging in lands on `DashboardPage.tsx`: only the apps, as large
  phone-launcher tiles (the app's colour as a gradient, a white glyph;
  `APP_ICONS` in `ui/AppTile.tsx` holds each app's glyph, colour and any
  renamed label). The gauge, stat cards and recent activity live in
  `StorePage.tsx` (`/store`, the "My Store" tile), with the store's
  settings one click away.
- **Consistent top bar** — search, notifications, workspace switcher, user
  menu never move between apps.
- **List / Kanban / Form, one switcher** — every resource in every app gets
  these three views for free from the generic schema-driven renderer
  (`web/src/ui/resource/*`). Apps only write a custom screen when the
  workflow genuinely needs one — POS register, pipeline kanban with
  drag-and-drop stage logic, Invoicing's "Pay with card" panel (real
  Stripe Elements, can't be a `FieldSpec`), Inventory's "Create purchase
  order" panel, and Web3's Treasury panel are the full list today, each
  justified by a doc comment at its own definition.
- **Smart buttons on records** — every record detail page gets a small
  strip of related-record counts (e.g. a Project's "3 Tasks", a
  Customer's "2 Invoices"), derived by scanning the app's own schema for
  any `reference` field pointing back at the current resource
  (`web/src/ui/resource/SmartButtons.tsx`) — not hand-built per app, and
  not configured anywhere; it falls out of declaring the relation once.
  A record's reference fields themselves (e.g. a Task's Project) render
  as a real searchable picker, not a raw id text box
  (`web/src/ui/resource/ReferenceInput.tsx`).
- **Apps catalog** — a single screen to see what's installed and enable more,
  instead of discovering features by accident in a menu tree.
- **Integrations settings** — the same "one screen, one list" instinct as
  the Apps catalog, applied to third-party providers instead of Friday's
  own apps: `web/src/shell/IntegrationsSettingsPage.tsx` is one card per
  provider (Stripe, Slack, Acyn Wallet, and the documented stubs — see
  `INTEGRATIONS.md`), each with a connect/edit form shaped by that
  provider's own config fields, backed by the kernel's credential store
  rather than a page per vendor.

## The app frame: every app looks like Apps & integrations (owner, 2026-11-22)

The owner's Apps & integrations page is the foundation every app builds
on. `shell/AppFrame.tsx` wraps every app route:

- **Left rail** with the app's icon and name, then its sections. On a
  phone the rail becomes one scrolling row. No pill-button navs inside
  pages; the rail is the only navigation within an app.
- **Sections follow the trade**, defined in `shell/appNav.ts`, one entry
  per app, with the pattern it follows named at the top: CRM after
  Pipedrive/HubSpot (pipeline first), Invoicing after Xero/QuickBooks
  (receivables, sales, the till, tax), Inventory after Shopify/Zoho
  (stock, purchasing, setup), Accounting after Xero/QuickBooks (reports,
  books, banking, close & tax), Projects after Linear/Jira/Zendesk,
  Fleets after Fleetio/Samsara, People after BambooHR/Gusto (team, pay,
  work). A new screen is added there, not as a link inside a page.
- **Search in the page head** (`.hub-search`), next to the title, on
  every list.
- **Hints are one small muted line** (`NavItem.hint`, shown above the
  page), only where a screen needs explaining. Never a banner.
- **Pickers never dead-end**: a reference picker with no match offers
  "+ Add … as a new …" and picks it (Xero/QuickBooks quick-create).
- **People is an app**: Minions' admin side (pay details, payroll,
  claims, staff sales, meetings) sits in People's rail at `/people/*`.
  `/minions/` is only ever the staff PWA, which staff are sent to.

## What we explicitly did not copy

No XML view-inheritance system, no deep ACL/record-rule graph, no dual
free/paywalled edition, no 80-item app menu. See `ARCHITECTURE.md` for the
reasoning.

No chatter/activity log either (Odoo's per-record message thread,
followers, and scheduled-activity reminders) — a real feature, and a real
gap, not a simplification we're claiming credit for. Smart buttons plus
each resource's own `created_at`/`updated_at` cover "what does this
relate to" and "when did it last change"; a full audit/comment trail on
every record is future work, not something to half-build.
