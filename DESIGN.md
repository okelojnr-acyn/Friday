# Friday Design System

Friday's interaction patterns are deliberately unoriginal: an app-launcher
home screen, a consistent top bar, list/kanban/form views with a view
switcher, smart action buttons and an activity log on records, and an "apps"
catalog to enable features per workspace. These patterns are proven at scale
in business software — there is no reason to reinvent navigation just to look
different. What Friday owns is the visual language layered on top of them.

## Principles

1. **Musou black, not gray-900.** The base surface is a true, deep black
   (`#0a0a0a`), not a dark-gray SaaS default. High contrast, no muddiness.
2. **One accent, used sparingly.** A single warm signal color carries all
   primary actions and status. Everything else is black / white / gray.
   Color is information, not decoration.
3. **No AI slop.** No gradient blobs, no glassmorphism, no drop-shadow soup,
   no decorative emoji in product UI, no stock-photo-style illustration.
   Flat surfaces, real typography, deliberate whitespace.
4. **Density where it matters, air where it doesn't.** Data tables and
   kanban cards are information-dense (this is work software); surrounding
   chrome (nav, headers, empty states) is generous and calm.
5. **One component kit, every app.** Every app renders through
   `web/src/ui` — no app ships its own buttons, inputs, or cards. This is
   what keeps 4+ independently-built apps feeling like one product, and
   what lets the whole UI restyle from one place.

## Tokens (`web/src/ui/tokens.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0a0a0a` | App background (musou black) |
| `--surface` | `#141414` | Cards, panels, table rows |
| `--surface-raised` | `#1c1c1c` | Modals, popovers, dropdowns |
| `--border` | `#2a2a2a` | Hairlines, dividers |
| `--text` | `#f5f5f0` | Primary text (off-white, not pure #fff) |
| `--text-muted` | `#9a9a94` | Secondary text, labels |
| `--accent` | `#e8a33d` | Primary actions, active states, links |
| `--accent-contrast` | `#0a0a0a` | Text/icon color on top of `--accent` |
| `--success` | `#3ecf8e` | Won/paid/synced states |
| `--danger` | `#e5484d` | Destructive actions, failed sync |
| `--radius` | `6px` | One radius, everywhere |
| `--font` | `Inter, system-ui, sans-serif` | One typeface, no display font |

Light mode exists (same structure, inverted neutrals) for users who need it,
but dark/musou-black is the default and the one the product is designed
around first.

## Patterns reused deliberately (proven, not reinvented)

- **App launcher home** — a grid of installed apps is the landing page after
  login. Familiar, scannable, and it doubles as the "what do I have access
  to" view.
- **Consistent top bar** — search, notifications, workspace switcher, user
  menu never move between apps.
- **List / Kanban / Form, one switcher** — every resource in every app gets
  these three views for free from the generic schema-driven renderer
  (`web/src/ui/resource/*`). Apps only write a custom screen when the
  workflow genuinely needs one (POS register, pipeline kanban with
  drag-and-drop stage logic).
- **Smart buttons + activity feed on records** — every record detail page
  gets a small strip of related-record counts (e.g. "3 Invoices") and a
  chronological activity/notes feed, generated from the same schema
  metadata, not hand-built per app.
- **Apps catalog** — a single screen to see what's installed and enable more,
  instead of discovering features by accident in a menu tree.

## What we explicitly did not copy

No XML view-inheritance system, no deep ACL/record-rule graph, no dual
free/paywalled edition, no 80-item app menu. See `ARCHITECTURE.md` for the
reasoning.
