# Friday: Product Requirements

`README.md` is the quickstart, `DESIGN.md` is the visual language,
`ARCHITECTURE.md` is how the pieces fit together. This is the "what are we
building and for whom" document those three point back to.

## Who this is for

A small or mid-size business that's outgrown spreadsheets but would
bounce off Salesforce/NetSuite/Odoo's setup cost and surface area --
targeting the owner-operator and the 2-30 person team, not the
enterprise buyer with a dedicated admin. The same person running the
business is usually the one configuring Friday, which is why "a
business can connect its own Stripe/Slack/Acyn Wallet account by pasting
in an API key" is a product requirement, not a nice-to-have: there's no
IT department to do a real integration project.

## What Friday is, today

Five app areas on one kernel (`ARCHITECTURE.md` has the technical shape):

- **CRM & Sales** -- leads through to a won or lost deal, with a per-
  opportunity note/activity timeline.
- **Invoicing** -- customers, invoices, payment status; takes a card
  payment directly (Stripe) and can bill on a recurring schedule.
- **Projects & Helpdesk** -- tasks and a kanban board, a support ticket
  queue with due dates and overdue surfacing, time tracking per task.
- **Inventory** -- products, stock on hand, a stock-move ledger, and a
  reorder workflow (suppliers, purchase orders, auto-restock on
  receiving).
- **POS** -- a cart register with barcode scanning, offline-first
  checkout, per-line discounts, and returns -- reading and writing the
  same product catalog and invoice ledger the other apps use, not a
  separate system to reconcile.
- **Web3** -- a business wallet (balances, payout requests, ISO
  20022-shaped credit transfers) via Acyn Wallet, Friday's first-class
  Web3 provider.

These aren't five separate products bolted together: a CRM deal becoming
an invoice, a POS sale decrementing stock, and an invoice's "pay with
card" button all flow through the same kernel event bus and the same
per-org trust boundary (`ARCHITECTURE.md`'s "Cross-app integration").
That's the actual product bet -- not "more features than a point
solution," but "one coherent system where the parts already talk to each
other," which is the thing a business actually feels when CRM, billing,
and stock are three different logins today.

## The integrations marketplace

Every business already has tools it won't give up for Friday --
whatever it uses for payments, calendars, and team chat. Rather than
Friday "winning" by replacing those, it's a product requirement that
connecting them is cheap:

- An org admin pastes an API key or webhook URL into Settings >
  Integrations. No OAuth app review, no partnership agreement, no
  professional-services engagement.
- A coding agent (Claude or otherwise) asked to "wire up Paystack" or
  "finish the Google Calendar integration" can do so by reading
  `INTEGRATIONS.md` and following the nearest code-ready adapter's
  shape -- the architecture is legible enough that this is a reasonable
  ask, not a multi-week integration project.
- Stripe, Slack, and Acyn Wallet are real, working reference
  implementations today; Calendly, Google Calendar, Paystack, Pesapal,
  MongoDB Atlas, Bridge, Alchemy, and Turnkey are documented, consistent
  stubs -- a forker finishes the ones their business actually needs.

This is deliberately an open-ended list, not a fixed roadmap: the
requirement is the *pattern* (one credential store, one adapter
interface per category, one settings screen), not any specific
provider. A new provider request is "add one file following the
pattern," not "redesign how integrations work."

## Web3 as a first-class area, not a bolt-on

Small businesses increasingly want a business wallet, cross-border
payouts, and eventually on/off-ramp -- without becoming a crypto company
to get it. Friday's position: `apps/web3` is a real app area (not a demo)
whose default path is **Acyn Wallet** -- a business creates an account
there, gets verified, and connects it to Friday exactly like connecting
Stripe. Acyn Wallet's own custody (Turnkey), on-chain reads (Alchemy),
and settlement verification (Bridge) are already handled on that side,
so a Friday deployment never needs to become its own custodian to offer
this. Forks that want to run their own custody stack instead of going
through Acyn Wallet can -- the direct Alchemy/Turnkey/Bridge adapters
exist as documented stubs for exactly that -- but it's not the path most
businesses should need.

## What "done" looks like for a new app area or integration

A new piece of Friday is done when:

1. It's declared, not hand-built, wherever the schema-driven UI contract
   already covers the workflow (`ResourceSpec`/`FieldSpec`) -- a hand-
   written screen is the exception, justified by a doc comment, not the
   default.
2. Cross-app effects go through the kernel's event bus or a documented
   HTTP call, never a direct import between apps or a cross-schema SQL
   join (`ARCHITECTURE.md`'s "Data ownership").
3. A stub is honestly a stub -- `NotImplementedError` and a docstring
   telling the next person exactly what to fill in, never a fake
   success response that looks finished until it's actually called in
   production.
4. It's documented in the file a forker or coding agent would actually
   open first: `INTEGRATIONS.md` for a provider, `ARCHITECTURE.md` for a
   structural piece, `docs/building-an-industry-site.md` for "how do I
   adapt this for my business."

## What Friday explicitly is not trying to be

Unchanged from `ARCHITECTURE.md`/`DESIGN.md`'s existing position, restated
here because it's a product decision as much as a technical one: not a
configurable-rules-engine ERP, not a dual free/paywalled product, not an
80-item app menu. The integrations marketplace and Web3 expand *what*
Friday connects to; they don't expand *how* Friday is configured --
still four roles, still no record-rule graph, still one design system
every app renders through.
