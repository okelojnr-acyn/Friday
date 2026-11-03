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

## Step 0 — Orient in the host repo, then ask before building anything

Read the host repo first -- don't ask the user anything you can answer
yourself by looking (framework, package manager, existing deploy config,
whether there's already an `/admin` area and what it's built with).
*Then* ask what you genuinely can't tell from the repo. Getting this
wrong is expensive here (wrong answer ⇒ a new subdomain, a new deploy
project, or a new database provisioned in the wrong place), so don't
guess past what you've actually confirmed. At minimum, confirm:

- What is this site built with, and where is it currently deployed?
  (Step 3 mirrors this -- get it right before provisioning anything.)
- Does it already have an admin area, and if so, is it a **separate
  app/deploy** from the public site, or just more routes inside the same
  app? (Step 1 branches on this.)
- Who is this for -- just the owner, or a team? If a team, does the host
  site already have user accounts/roles for staff, or would this be the
  first internal-tool login they'd be setting up?
- Is there an existing domain/DNS provider to add a subdomain under
  (Step 2), and does the user control DNS for it from here?
- Where's the database, if one already exists for this site (Step 4)?
- Any existing auth the admin area should share or stay independent
  from? (Friday has its own login -- confirm the user is fine with a
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
is a real architectural fork, not a default to silently pick.

Once there's a separate admin app (existing or freshly created), continue
to Step 2 against *that* app, not the public site.

## Step 2 — Add the Friday launcher to the (now-separate) admin app

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
  wherever Friday's `web/` is deployed (Step 3).
- Nothing on Friday's side changes — it doesn't care what domain serves
  its static build, as long as `VITE_KERNEL_URL` (Step 3) still resolves.

**True SSO (one login for both) is out of scope for this procedure** —
it needs an actual identity-provider decision (OIDC between the host
site's auth and Friday's kernel) that's a separate, larger piece of
work. Say so explicitly if the user asks for it rather than
half-building it.

## Step 3 — Deploy Friday

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
| **A VPS / already self-hosting** | Simplest path of all: `docker compose -f infra/docker-compose.yml up -d` directly on that box. Put a reverse proxy (nginx/Caddy) in front for TLS + the subdomain from Step 2. |
| **Somewhere else / unsure** | Ask. Don't guess a platform with real billing implications. |

Whatever the target, the kernel needs real values for `JWT_SECRET` and
`KERNEL_EVENTS_TOKEN` (generate real random secrets — don't ship the
`dev-only-change-me` defaults anywhere but localhost), and `CORS_ORIGIN`
set to wherever `web/` actually ends up being served from.

## Step 4 — Database

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
  to the deploy target from Step 3 (RDS alongside AWS, Supabase/Neon
  alongside Vercel, or just Postgres-in-docker-compose alongside a VPS)
  — don't introduce a new cloud vendor the rest of the deploy doesn't
  already use.

Once `DATABASE_URL` is set for the kernel and every app, run migrations
exactly like `README.md`'s quickstart does — the kernel migrates itself
on startup; each Python app needs its migration command run once:
`python -m friday_common.migrate apps/<app> <app>` per app (see
`infra/docker-compose.yml` for the exact invocations if deploying
without compose).

## Step 5 — Verify, end to end

1. Hit the kernel's `/healthz`.
2. Hit each app's `/healthz` through the kernel's proxy:
   `curl <kernel-url>/api/crm/opportunities` with a real bearer token
   should return `[]` on a fresh install, not an error.
3. Open the web URL, register an org, confirm the dashboard loads.
4. Click the launcher button added in Step 2 from the host site's admin
   area and confirm it actually lands on that same login.

Don't report this as done until step 3 and 4 both actually happened —
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
