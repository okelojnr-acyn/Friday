# Legal document templates

**These are templates, not legal advice, and not ready to publish as
written.** Nobody on this project is your lawyer. Every file in this
directory needs a qualified lawyer, licensed in the jurisdiction(s) you
actually operate in, to review it against your real business before you
put it in front of a real customer or user. Shipping one of these
unedited is worse than having no policy at all -- it makes promises
("we never do X") that may not match what your actual deployment does.

## Why these exist

Friday is software you (or your org) deploy and run -- there is no
"Friday Inc." operating a hosted service on your behalf. That changes
what a privacy policy/terms of service actually need to say: **you**
are the data controller and the service provider, not this project.
Every `{{PLACEHOLDER}}` in these files is a spot where that has to be
made concrete -- your entity name, your jurisdiction, your contact
address, which third-party providers you've actually connected (see
`INTEGRATIONS.md`), and how long you actually retain data.

## What to fill in before any of this is usable

- `{{COMPANY_NAME}}` / `{{COMPANY_ENTITY}}` -- the legal entity running
  this deployment.
- `{{JURISDICTION}}` -- governing law/venue; get this from your lawyer,
  not from guessing.
- `{{CONTACT_EMAIL}}` -- a real, monitored address for privacy/legal
  inquiries.
- `{{EFFECTIVE_DATE}}` -- when this version takes effect.
- The **connected integrations list** in `PRIVACY_POLICY_TEMPLATE.md` --
  only list providers you've actually connected (Settings >
  Integrations). Listing one you haven't connected is as wrong as
  omitting one you have.
- Data retention periods, deletion procedures, and any
  jurisdiction-specific disclosures (GDPR, CCPA, or whatever applies to
  where your users/customers actually are) -- these are genuinely
  jurisdiction-dependent and this template doesn't guess at them.

## What Claude (or any coding agent) should do with these during an install

Per `INSTALL.md`'s closing checklist: point the user at this directory,
explain the disclaimer above in plain terms, help them fill in the
mechanical placeholders (company name, contact email, which integrations
are actually connected) if asked, and explicitly recommend a lawyer
review before publishing -- but never present a filled-in version of
these as "done" or "compliant." That's not a determination a coding
agent (or this template) is positioned to make.
