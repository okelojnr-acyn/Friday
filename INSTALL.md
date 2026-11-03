# Installing Friday into an existing site

This file is a procedure for an AI coding agent (Claude Code, Codex CLI,
or similar) to follow when a user opens a *different* project — their
own website — and asks to add Friday to it, pointing at this repo's
GitHub URL. It is not a quickstart for Friday itself (see `README.md`
for that); it's "how do I bolt Friday onto something that already
exists."

**The one thing to get right first**: Friday is not a component or a
library you import into another app. It's a full multi-service
application (a Go kernel, Python services, Postgres, a React web
shell — see `ARCHITECTURE.md`). "Installing" Friday into a site means
**deploying Friday as its own service** and adding a way to *get to* it
from the site's admin area — a launcher link, ideally one that feels
like part of the same product. It does not mean copying Friday's source
into the host repo or merging the two codebases. Don't let the user
talk you into the merge version; it creates exactly the routing/auth/
deploy conflicts this procedure exists to avoid.

## Step 0 — Research the business, not just the stack

Before asking the user anything, read the host repo for what it's
actually *about* — not just its framework. This is what lets you
propose a concrete Friday app set, a concrete integration list, and a
data-import plan instead of guessing, and it's what keeps the next step
(Step 1) down to the infra questions research genuinely can't answer,
instead of a long interview that starts from zero.

Read whatever a repo of this kind actually has:

- The manifest's name/description/keywords (`package.json` for
  Node-based stacks, the equivalent for others).
- `README.md`'s first paragraph or section.
- Nav/route labels and page titles — grep router files, `<nav>` markup,
  `sitemap.xml`, or CMS routes for what the site calls its own primary
  sections.
- Pricing/services/products page copy, if present.
- Any seed fixtures, CMS content, or ORM schema (`schema.prisma`,
  Django `models.py`, Rails `schema.rb`, a `products.json` fixture,
  etc.) that already enumerates products, services, or customers —
  this is exactly what "Importing existing data" below reads from.
- Anything that already names a payment/calendar/chat provider (a
  `STRIPE_*` key in `.env.example`, a Calendly embed, a Slack webhook
  URL mentioned anywhere) — cross-reference against `INTEGRATIONS.md`'s
  provider list rather than asking the user to re-list what they
  already have wired up.

Write **one** scratch file, `.friday/install-profile.md` (gitignore it
in the host repo if you create a `.gitignore` entry there — it's a
working note for this install, not something to commit), instead of a
list of questions:

```markdown
# Friday install profile

**Inferred industry**: <e.g. "boutique retail", "B2B consultancy", "repair shop"> (confidence: high/medium/low)
**Evidence**: <the specific files/strings that led to this>

**Proposed Friday apps**: <subset of crm, invoicing, projects, inventory, pos, web3, accounting, minions>
**Why**: <one line per app>

**Proposed integrations**: <provider: code-ready or stub, and what was found that suggests it>

**Proposed data import**: <what existing data was found, and roughly how many rows/records of each>
```

Show this file to the user as **one consolidated confirmation** — "here's
what I found and what I'd install; tell me what's wrong, otherwise I'll
proceed" — rather than a question for each line. This is what "without
overwhelming the installer with questions" means concretely: one
artifact to correct, not a dozen round trips. Step 1 still asks
directly for anything this research genuinely couldn't answer (deploy
target, DNS control, team size, existing auth) — don't guess those.

### Self-adjusting the admin portal, once an org exists

"Self-adjust" is a concrete action, not a vibe: once the first org is
registered (end of Step 6's verification), call the kernel's existing
per-org install toggle once for each app in the confirmed profile's
app set — this endpoint already exists, no new kernel code needed:

```bash
curl -X POST "$KERNEL_URL/orgs/apps/<app>/install" -H "Authorization: Bearer $OWNER_TOKEN"
```

If the owner later decides an app doesn't fit after all, the same path
with `DELETE` instead of `POST` uninstalls it.

This is a **per-org** toggle. If the fork is instead meant to
permanently relabel an app for *every* org this deployment will ever
serve — a salon wants "Projects" to always read "Bookings," not just
for this one org — that's a source edit to
`kernel/internal/registry/registry.go`'s `Label`/`Description` fields
(documented in `docs/building-an-industry-site.md`), not this endpoint.
Don't reach for the global edit on a normal single-org install.

### Importing existing data

No generic importer can live in Friday's own repo — every host's field
names differ. `scripts/host-data-import-template.py` is a short,
fill-in-the-blanks script: copy it into the **host repo** (it's not
meant to be committed back to Friday), fill in the field mapping from
what Step 0's research already found, and run it once against the
newly-deployed Friday instance:

```bash
python host-data-import-template.py --kernel-url https://friday.example.com --token $OWNER_TOKEN
```

It calls bulk-create endpoints that already exist for exactly this —
`POST /api/inventory/products/bulk` for a discovered product/service
list, `POST /api/invoicing/customers/bulk` for a discovered customer
list — batched, not one row per request. Show the created counts to the
user before moving on ("imported 42 products, 18 customers") so a bad
field mapping is caught immediately, not discovered later in a
half-populated catalog.

## Step 1 — Orient in the host repo's infrastructure, then ask before building anything

Step 0 covered the business; this step covers the stack. Read the host
repo for what you can answer yourself by looking (framework, package
manager, existing deploy config, whether there's already an `/admin`
area and what it's built with). *Then* ask what you genuinely can't
tell from the repo. Getting this wrong is expensive here (wrong answer
⇒ a new subdomain, a new deploy project, or a new database provisioned
in the wrong place), so don't guess past what you've actually
confirmed. At minimum, confirm:

- What is this site built with, and where is it currently deployed?
  (Step 4 mirrors this — get it right before provisioning anything.)
- Does it already have an admin area, and if so, is it a **separate
  app/deploy** from the public site, or just more routes inside the same
  app? (Step 2 branches on this.)
- Who is this for — just the owner, or a team? If a team, does the host
  site already have user accounts/roles for staff, or would this be the
  first internal-tool login they'd be setting up?
- Is there an existing domain/DNS provider to add a subdomain under
  (Step 3), and does the user control DNS for it from here?
- Where's the database, if one already exists for this site (Step 5)?
- Any existing auth the admin area should share or stay independent
  from? (Friday has its own login — confirm the user is fine with a
  second, separate login rather than assuming SSO is wanted; see the
  SSO note at the end of this file.)

Don't scaffold, provision, or deploy anything until these are answered.
A wrong assumption here is a live subdomain or cloud resource to clean
up, not just a line of code to revert.

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

## Step 2 — If admin isn't already separate, say so and stop there

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
is a real architectural fork, not a default to silently pick.

Once there's a separate admin app (existing or freshly created), continue
to Step 3 against *that* app, not the public site.

## Step 3 — Add the Friday launcher to the (now-separate) admin app

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
  wherever Friday's `web/` is deployed (Step 4).
- Nothing on Friday's side changes — it doesn't care what domain serves
  its static build, as long as `VITE_KERNEL_URL` (Step 4) still resolves.

**True SSO (one login for both) is out of scope for this procedure** —
it needs an actual identity-provider decision (OIDC between the host
site's auth and Friday's kernel) that's a separate, larger piece of
work. Say so explicitly if the user asks for it rather than
half-building it.

## Step 4 — Deploy Friday

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
| **A VPS / already self-hosting** | Simplest path of all: `docker compose -f infra/docker-compose.yml up -d` directly on that box. Put a reverse proxy (nginx/Caddy) in front for TLS + the subdomain from Step 3. |
| **Somewhere else / unsure** | Ask. Don't guess a platform with real billing implications. |

Whatever the target, the kernel needs real values for `JWT_SECRET` and
`KERNEL_EVENTS_TOKEN` (generate real random secrets — don't ship the
`dev-only-change-me` defaults anywhere but localhost), and `CORS_ORIGIN`
set to wherever `web/` actually ends up being served from.

## Step 5 — Database

Ask: **"Where's your database, or where do you want one?"** Friday needs
one Postgres instance — the kernel owns a `core` schema, each app owns
its own schema in the *same* database (see `ARCHITECTURE.md`'s "Data
ownership") — so this is provisioning one database, not one per app.

- Already have Postgres somewhere (RDS, Supabase, Neon, a VPS)? Just
  point `DATABASE_URL` at it. Nothing Friday-specific needed beyond that
  one connection string, reused (with the right driver prefix — `postgres://`
  for the kernel, `postgresql+asyncpg://` for the Python apps) across
  every service.
- Starting from nothing? Recommend whichever managed Postgres is closest
  to the deploy target from Step 4 (RDS alongside AWS, Supabase/Neon
  alongside Vercel, or just Postgres-in-docker-compose alongside a VPS)
  — don't introduce a new cloud vendor the rest of the deploy doesn't
  already use.

Once `DATABASE_URL` is set for the kernel and every app, run migrations
exactly like `README.md`'s quickstart does — the kernel migrates itself
on startup; each Python app needs its migration command run once:
`python -m friday_common.migrate apps/<app> <app>` per app (see
`infra/docker-compose.yml` for the exact invocations if deploying
without compose).

## Step 6 — Verify, end to end

1. Hit the kernel's `/healthz`.
2. Hit each app's `/healthz` through the kernel's proxy:
   `curl <kernel-url>/api/crm/opportunities` with a real bearer token
   should return `[]` on a fresh install, not an error.
3. Open the web URL, register an org, confirm the dashboard loads.
4. Click the launcher button added in Step 3 from the host site's admin
   area and confirm it actually lands on that same login.
5. Run the app-install toggle calls from Step 0's "Self-adjusting the
   admin portal" section for the confirmed app set, and the data import
   from "Importing existing data" if there was anything to import.

Don't report this as done until steps 3 and 4 both actually happened —
a server returning 200 on `/healthz` is not the same as a user being
able to click a button and get into Friday.

## What this procedure deliberately doesn't do

- It doesn't merge Friday's source into the host repo. If the user
  insists they want that, push back once (explain the cost: two
  different language/deploy stacks jammed into one repo, no clean
  update path for pulling in future Friday changes) and only proceed if
  they still want it after hearing that.
- It doesn't build SSO. A shared login between the host site and Friday
  is real, separate work — flag it as a follow-up, don't half-do it.
- It doesn't pick a cloud platform for the user. Every "where" in this
  file is a question to ask, not a default to assume.
- It doesn't build a universal data importer. `host-data-import-template.py`
  is a template an agent fills in per-host, not a generic ETL tool —
  every host's schema is different, and that mapping step is exactly
  the part that needs a human (or an agent that's actually read the
  host's code) to get right.
