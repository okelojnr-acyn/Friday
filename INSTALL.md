# Installing Friday into an existing site

This file is a procedure for an AI coding agent (Claude Code, Codex CLI,
or similar) to follow when a user opens a *different* project — their
own website — and asks to add Friday to it, pointing at this repo's
GitHub URL. It is not a quickstart for Friday itself (see `README.md`
for that); it's "how do I bolt Friday onto something that already
exists."

**The one thing to get right first**: Friday is not a component or a
library you import into another app. It's a full multi-service
application (a Go kernel, five Python services, Postgres, a React web
shell — see `ARCHITECTURE.md`). "Installing" Friday into a site means
**deploying Friday as its own service** and adding a way to *get to* it
from the site's admin area — a launcher link, ideally one that feels
like part of the same product. It does not mean copying Friday's source
into the host repo or merging the two codebases. Don't let the user
talk you into the merge version; it creates exactly the routing/auth/
deploy conflicts this procedure exists to avoid.

**Keep going until you're actually sure, not until you've run out of
obvious questions.** This procedure is written as discrete steps for
your own tracking, not as a script to execute mechanically end to end.
If something about the host site's data model, business type, or
existing payment setup is still unclear after Step 0, go read more of
its code before writing anything — a wrong guess here costs the user a
live subdomain, a cloud resource, or a duplicated payment integration to
clean up later, not just a line to revert.

## Step 0 — Orient in the host repo, then ask before building anything

Read the host repo first -- don't ask the user anything you can answer
yourself by looking (framework, package manager, existing deploy config,
whether there's already an `/admin` area and what it's built with, what
the site actually *collects* -- a customers table, an orders table, a
bookings table, none of the above). *Then* ask what you genuinely can't
tell from the repo. At minimum, confirm:

- What is this site built with, and where is it currently deployed?
  (Step 5 mirrors this -- get it right before provisioning anything.)
- Does it already have an admin area, and if so, is it a **separate
  app/deploy** from the public site, or just more routes inside the same
  app? (Step 1 branches on this.)
- **What kind of business is this, and what does the site already do
  for it?** An e-commerce storefront with its own checkout/inventory is
  a fundamentally different install than a services site with a contact
  form and nothing transactional at all. This determines which Friday
  apps actually earn a place (Step 2) and whether there's existing data
  worth importing (Step 3) or an existing payment setup worth reusing
  instead of duplicating (Step 5).
- Who is this for -- just the owner, or a team? If a team, does the host
  site already have user accounts/roles for staff, or would this be the
  first internal-tool login they'd be setting up?
- Is there an existing domain/DNS provider to add a subdomain under
  (Step 4), and does the user control DNS for it from here?
- Where's the database, if one already exists for this site (Step 6)?
- Any existing auth the admin area should share or stay independent
  from? (Friday has its own login -- confirm the user is fine with a
  second, separate login rather than assuming SSO is wanted; see the
  SSO note at the end of this file.)

Don't scaffold, provision, or deploy anything until these are answered.

Heuristics for "separate app already":
- A monorepo with something like `apps/admin` + `apps/web`, each with
  its own `package.json`/deploy config.
- A subdomain already in play for admin (`admin.example.com` in DNS/
  `vercel.json`/nginx config/etc.), served by a different deploy than the
  main domain.
- A clearly distinct framework/stack for admin vs. the public site.

If none of that is true — admin is just `/admin/*` routes inside the
same Next.js/Rails/whatever app as the public marketing pages — treat it
as **not separate**, even if there's an `/admin` folder of components.

## Step 1 — If admin isn't already separate, say so and stop there

Don't install Friday into a shared app. Recommend splitting admin out
first, and explain why in one sentence: the public site and an internal
business tool have different audiences, different risk profiles, and
you don't want a business-suite launcher button shipping in the same
bundle as the marketing site. Concretely, present (don't just assume)
one of:

- **New deploy, same repo**: if the framework supports it cheaply (a
  second Next.js app in the same monorepo, a second Vite app), scaffold
  `apps/admin` next to the existing app, move existing `/admin/*` pages
  into it, point a new subdomain at it.
- **New repo entirely**: if splitting in-place is awkward, a fresh
  minimal admin app (can be as small as "one protected page with a
  button") in its own repo/deploy is often less work than it sounds —
  it only needs to exist to host the Friday launcher and whatever
  internal tools the site owner already wanted separated anyway.

Ask the user which they'd rather do before scaffolding anything — this
is a real architectural fork, not a default to silently pick. If the
existing admin area already has real features (even a thin one -- a
simple order list, a basic contact-form inbox), carry those over into
the new app rather than discarding them; Friday is meant to fill gaps,
not replace something that already works.

Once there's a separate admin app (existing or freshly created), continue
to Step 2 against *that* app, not the public site.

## Step 2 — Decide which parts of Friday actually earn a place

Friday is five app areas (CRM, Invoicing, Projects & Helpdesk, Inventory,
POS) plus Web3 and an integrations layer -- not every business needs all
of it, and installing the full set unexamined is the same mistake as
skipping this step entirely. Use `docs/building-an-industry-site.md`'s
table as your starting point, then adjust for what Step 0 actually
found:

- **Admin area has little or no existing functionality** (a services
  business with just a contact form, say): Friday fills almost the
  whole gap. Enable CRM + Invoicing + Projects & Helpdesk by default;
  skip Inventory/POS unless the business actually stocks or sells
  physical goods.
- **Admin area already has real e-commerce features** (its own
  checkout, product catalog, order management): don't install
  Inventory/POS to duplicate what already works. Either leave those
  apps uninstalled entirely, or install Inventory specifically to get
  its reorder/stock-ledger features *on top of* the existing catalog
  (see Step 3 for how that data gets linked, not duplicated) --ask the
  user which they want rather than assuming.
- **Anything Web3-shaped** (a wallet, crypto payments) is opt-in --
  only relevant if the business actually asked for it. Don't install
  it by default just because it exists.

This decision changes what you actually enable in the Apps Catalog
(`/apps` once Friday is running) and the deploy env vars in Step 5 --
settle it before Step 4, not after.

## Step 3 — Reading the host site's existing data

If the host site already has customers, orders, products, or bookings
worth seeing inside Friday, **do not** reach across databases to read
them directly -- Friday's own architecture rule (`ARCHITECTURE.md`'s
"Data ownership": no cross-schema joins, ever, even within Friday
itself) applies just as hard to a foreign database you don't control
the shape of. The correct pattern is an **import through Friday's own
APIs**, the same way a human filling in forms would, just automated:

- **Customers → CRM/Invoicing**: read the host site's customer/user
  table, `POST /api/crm/opportunities` or `/api/invoicing/customers`
  for each one. One-time backfill, or re-run periodically if the host
  site keeps gaining customers Friday doesn't know about yet.
- **Products → Inventory**: `POST /api/inventory/products/bulk`
  (`apps/inventory/app/main.py`) takes a batch in one call -- built for
  exactly this. Map the host site's product fields to Friday's
  (`name`, `sku`, `barcode`, `price_cents`, `kind: "product"|"service"`)
  and a single bulk-import script covers a full catalog.
  physical products use `kind: "product"`, pure services use `kind:
  "service"` (no stock tracking) — see `apps/inventory`'s own docs.
- **Orders/bookings → Invoicing or Projects**: there's no generic bulk
  endpoint for invoices yet (each one needs line items -- see
  `InvoiceCreateModal.tsx` for the shape), so this is a small
  purpose-written script calling `POST /api/invoicing/invoices` per
  historical order, not a reusable Friday feature. Write it, run it
  once for the backfill, and note in your handoff to the user whether
  it needs to run again (e.g. a nightly sync) or was a one-time import.
- **Ongoing sync, not just a backfill**: if new orders/customers should
  keep flowing into Friday after go-live, this needs an actual
  integration point -- a webhook on the host site's checkout calling
  the matching Friday API, or a scheduled job. This is genuinely
  bespoke per host site; don't promise it works out of the box, build
  the specific call the host site's order-creation flow needs.

Keep touching the code on both sides until you're confident the field
mapping is right (currency units especially -- Friday stores money as
integer cents everywhere, `amountInputToCents`/`price_cents` naming is
your signal for this) -- a bulk import with silently wrong units is
worse than no import.

## Step 4 — Add the Friday launcher to the admin app

Two options, cheapest first. Ask the user which they want — don't
silently pick the fancier one.

**Option A — a link/button that opens Friday in its own tab** (default
recommendation; minutes of work, zero auth-integration risk):

```html
<a href="https://friday.example.com" target="_blank" rel="noopener">
  Open Friday
</a>
```

Friday manages its own login/session — the user signs into Friday once,
same as they'd sign into any other SaaS tool linked from an internal
tools page. This is correct and sufficient for most cases; don't
over-build.

**Option B — feels like one product (subdomain + reverse proxy, no SSO
yet)**: same button, but `https://friday.example.com` is a subdomain of
the site's own domain (not Friday's default host), so it reads as part
of the same product even though it's a separate login. This needs:
- DNS: `friday.example.com` (or `admin.example.com/friday` via a reverse
  proxy rewrite, if the host doesn't want a new subdomain) pointed at
  wherever Friday's `web/` is deployed (Step 5).
- Nothing on Friday's side changes — it doesn't care what domain serves
  its static build, as long as `VITE_KERNEL_URL` (Step 5) still resolves.

**True SSO (one login for both) is out of scope for this procedure** —
it needs an actual identity-provider decision (OIDC between the host
site's auth and Friday's kernel) that's a separate, larger piece of
work. Say so explicitly if the user asks for it rather than
half-building it.

## Step 5 — Deploy Friday, and connect the easy integrations while you're there

Ask: **"Where is your current site deployed?"** — mirror that, don't
default to a platform the user didn't ask for. Friday's pieces split
into two shapes that matter here:

- `web/` — a static Vite build. Fits any static host trivially.
- `kernel/` (Go) + `apps/*` (Python/FastAPI) — long-running servers, not
  serverless-shaped. They need a container host, not a static/serverless
  platform.

| Current site on... | Do this |
|---|---|
| **Vercel/Netlify** | Deploy `web/` there directly (it's already a Vite app — `vercel.json`/Netlify build settings: build command `npm run build` in `web/`, output `web/dist`). Deploy `kernel/` + `apps/*` to a container host instead — Fly.io or Railway are the least-setup options (`fly launch` / `railway up` per service, or one `fly.toml` per app). Point the static site's `VITE_KERNEL_URL` env var at wherever the kernel ends up. |
| **AWS** | `infra/docker-compose.yml` already defines every service — translate it close to 1:1 into ECS Fargate (one task definition per service, or one task with multiple containers if you want them co-located) behind an ALB, Postgres on RDS. `web/`'s static build can go to S3+CloudFront instead of a Fargate task if you'd rather not run it as a container. |
| **A VPS / already self-hosting** | Simplest path of all: `docker compose -f infra/docker-compose.yml up -d` directly on that box. Put a reverse proxy (nginx/Caddy) in front for TLS + the subdomain from Step 4. |
| **Somewhere else / unsure** | Ask. Don't guess a platform with real billing implications. |

Whatever the target, the kernel needs real values for `JWT_SECRET` and
`KERNEL_EVENTS_TOKEN` (generate real random secrets — don't ship the
`dev-only-change-me` defaults anywhere but localhost), `WEBAUTHN_RP_ID`
set to the real domain `web/` is served from (passkeys fail to verify
otherwise -- see `.env.example`), and `CORS_ORIGIN` set the same way.

**While you're setting up env vars, finish these three -- they're cheap
and most installs want all of them:**

1. **Email (OTP delivery)** -- Friday logs OTP codes to stdout until a
   real mail transport is configured, which is fine for your own
   testing but not for a real user waiting on a code. Recommended:
   [Resend](https://resend.com) -- sign up, verify a sending domain (or
   use their shared test domain while you're still setting up), create
   an API key under Dashboard → API Keys, set `RESEND_API_KEY` and
   `MAIL_FROM`. Tell the user exactly this -- where to sign up, which
   dashboard screen the key lives on -- don't just drop the env var
   name on them. If they already run their own SMTP relay and don't
   want a second vendor, `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`
   works instead (see `.env.example`'s comments for both paths).
2. **CoinGecko (market data)** -- needs nothing. It works the moment
   Web3 is enabled, free tier, no signup. Just confirm it's actually
   reachable from wherever you deployed (Settings > Integrations >
   CoinGecko, or `apps/web3`'s Market page) rather than assuming --
   some locked-down hosting environments block outbound HTTPS to
   arbitrary hosts, and this is the cheapest thing to verify that would
   catch it.
3. **A payment provider**, if Invoicing or POS will actually take
   payments. Figure out which situation applies before picking one:
   - **The host site already has a live payment integration** (its own
     Stripe/PayPal/etc. on checkout): don't set up a second, competing
     one inside Friday for the same transactions. Either leave Friday's
     payment integrations disconnected and use Friday purely for
     invoicing/record-keeping against payments the host site already
     processes, or scope Friday's payment use to a channel the host
     site's checkout doesn't cover (e.g. the POS register for in-person
     sales, while the website keeps its own online checkout).
   - **No existing payment setup, or Friday's POS/Invoicing is meant to
     be the primary payment channel**: Stripe is Friday's code-ready
     reference integration (`INTEGRATIONS.md#stripe`) -- ask the user
     to sign up at stripe.com, grab a secret key from Dashboard →
     Developers → API keys, connect it in Settings > Integrations. If
     the business is somewhere Stripe doesn't serve well (parts of
     Africa, say), Paystack or Pesapal are the documented alternatives
     — but those are stubs today (`INTEGRATIONS.md`), so say so plainly:
     finishing one is a real, if contained, piece of work, not a
     config toggle the way Stripe is.

## Step 6 — Database

Ask: **"Where's your database, or where do you want one?"** Friday needs
one Postgres instance — the kernel owns a `core` schema, each app owns
its own schema in the *same* database (see `ARCHITECTURE.md`'s "Data
ownership") — so this is provisioning one database, not five.

- Already have Postgres somewhere (RDS, Supabase, Neon, a VPS)? Just
  point `DATABASE_URL` at it. Nothing Friday-specific needed beyond that
  one connection string, reused (with the right driver prefix — `postgres://`
  for the kernel, `postgresql+asyncpg://` for the Python apps) across
  every service.
- Starting from nothing? Recommend whichever managed Postgres is closest
  to the deploy target from Step 5 (RDS alongside AWS, Supabase/Neon
  alongside Vercel, or just Postgres-in-docker-compose alongside a VPS)
  — don't introduce a new cloud vendor the rest of the deploy doesn't
  already use.

Once `DATABASE_URL` is set for the kernel and every app, run migrations
exactly like `README.md`'s quickstart does — the kernel migrates itself
on startup; each Python app needs its migration command run once:
`python -m friday_common.migrate apps/<app> <app>` per app (see
`infra/docker-compose.yml` for the exact invocations if deploying
without compose).

## Step 7 — Security and legal, before calling this done

Friday ships with real protections already on by default (rate limiting,
Row-Level Security, parameterized queries throughout, no cookies, basic
response hardening -- the full list is `SECURITY.md`). Nothing in this
step is optional security work Friday is missing; it's the handful of
things that are inherently *this deployment's* decision, not something
shippable as a generic default:

1. **Point the user at `legal/`** -- Privacy Policy, Terms of Service,
   and Cookie Policy templates. Read `legal/README.md` first. Help fill
   in the mechanical placeholders if asked (company name, contact
   email, which integrations from Step 5 are actually connected), but
   **never present a filled-in version as done or compliant** -- that
   determination needs this deployment's own lawyer, not a coding
   agent. Say this to the user plainly, don't bury it.
2. **Confirm the production secrets are real secrets.** `JWT_SECRET`,
   `KERNEL_EVENTS_TOKEN`, and any payment/integration API keys must not
   be the `dev-only-change-me` placeholders or a key copy-pasted into a
   committed file. Check `.gitignore` actually covers whatever `.env`
   equivalent this deployment uses.
3. **If this deployment sits behind a load balancer or reverse proxy**,
   set `TRUST_PROXY_HEADERS=true` only if that proxy actually
   overwrites `X-Forwarded-For` with the real client IP (nginx/Caddy/an
   ALB do this correctly by default) -- enabling it behind something
   that doesn't would let the rate limiter be trivially bypassed by a
   client sending a fake header. Leave it unset if you're not sure.
4. **If you added cookies anywhere** (an analytics tool, a marketing
   page, a CDN affinity cookie) that Friday itself doesn't set, update
   the Cookie Policy template to disclose them -- it ships honestly
   describing Friday's own no-cookie auth, which stops being accurate
   the moment anything else in the deployment sets one.

## Step 8 — Verify, end to end

1. Hit the kernel's `/healthz`.
2. Hit each app's `/healthz` through the kernel's proxy:
   `curl <kernel-url>/api/crm/opportunities` with a real bearer token
   should return `[]` (or real imported data, if Step 3 ran) on a fresh
   install, not an error.
3. Open the web URL, register an org, confirm the dashboard loads, and
   confirm only the apps decided on in Step 2 are installed.
4. Click the launcher button added in Step 4 from the host site's admin
   area and confirm it actually lands on that same login.
5. If Step 3's import ran, spot-check a handful of imported records in
   the actual Friday UI, not just the API response.
6. If a payment provider was connected in Step 5, run one real test
   transaction through it before calling this live.

Don't report this as done until steps 3, 4, 5, and 6 (as applicable)
all actually happened — a server returning 200 on `/healthz` is not the
same as a user being able to click a button, see their real data, and
take a payment.

## What this procedure deliberately doesn't do

- It doesn't merge Friday's source into the host repo. If the user
  insists they want that, push back once (explain the cost: two
  different language/deploy stacks jammed into one repo, no clean
  update path for pulling in future Friday changes) and only proceed if
  they still want it after hearing that.
- It doesn't build SSO. A shared login between the host site and Friday
  is real, separate work — flag it as a follow-up, don't half-do it.
- It doesn't pick a cloud platform, a payment provider, or a legal
  document's actual content for the user. Every "where"/"which" in this
  file is a question to ask, not a default to assume.
