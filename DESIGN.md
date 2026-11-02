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
   what keeps 4+ independently-built apps feeling like one product, and
   what lets the whole UI restyle from one place.

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

- **Dashboard home, app launcher underneath** — logging in lands on
  `DashboardPage.tsx`: a hero gauge (CRM win rate), a `StatCard` grid pulled
  from whatever apps are installed (pipeline value, outstanding/collected
  invoicing, open tasks/tickets, low stock), a `.band-ink` recent-activity
  feed, then the familiar app-tile grid below. Each stat card is a real
  number from that app's own list endpoint, computed client-side the same
  way a kanban column's dollar sum already was — no new backend aggregation
  endpoint, and a card simply doesn't render if its app isn't installed.
- **Consistent top bar** — search, notifications, workspace switcher, user
  menu never move between apps.
- **List / Kanban / Form, one switcher** — every resource in every app gets
  these three views for free from the generic schema-driven renderer
  (`web/src/ui/resource/*`). Apps only write a custom screen when the
  workflow genuinely needs one (POS register, pipeline kanban with
  drag-and-drop stage logic).
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
