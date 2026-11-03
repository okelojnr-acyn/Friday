<!--
TEMPLATE -- read legal/README.md before using this file for anything.
Not legal advice. Requires lawyer review before publishing. Every
{{PLACEHOLDER}} must be filled in with your actual details.
-->

# Cookie Policy

**Effective date:** {{EFFECTIVE_DATE}}

## Friday itself sets no cookies

This is the one section of this directory that isn't a fill-in-the-
blank: as shipped, Friday's web app does not use cookies for
authentication or session management. Your session token is held in
your browser's `localStorage` and sent as an `Authorization` header,
not a cookie (see `ARCHITECTURE.md`/`SECURITY.md` in the Friday
repository). There is nothing to disclose here unless you've changed
that, or added something else that sets cookies -- see below.

## When you *do* need to fill this in

If your deployment adds any of the following, update this policy to
disclose it before you ship it:

- **Analytics** (Google Analytics, Plausible, PostHog, etc.) --
  disclose what it tracks and whether it sets cookies or uses
  cookieless tracking.
- **A marketing/landing site** in front of this deployment, if it uses
  its own cookies (common for ad pixels, A/B testing tools) --
  disclose those separately from the app itself.
- **A third-party integration's own cookies** -- e.g. if a connected
  provider's embedded widget (not Friday's own code) sets a cookie in
  the user's browser. Check that provider's own cookie disclosure and
  summarize it here.
- **A reverse proxy or CDN** in front of this deployment that sets its
  own cookies (e.g. a load-balancer affinity cookie) -- disclose if
  applicable.

## Template disclosure table (fill in only what applies)

| Cookie/storage name | Set by | Purpose | Duration |
|---|---|---|---|
| `friday.session` (localStorage, not a cookie) | Friday itself | Holds your session token | Until you log out or clear browser storage |
| {{NAME}} | {{WHO SETS IT}} | {{WHAT IT DOES}} | {{HOW LONG}} |

## Contact

{{CONTACT_EMAIL}}
