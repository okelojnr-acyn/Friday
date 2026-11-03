<!--
TEMPLATE -- read legal/README.md before using this file for anything.
Not legal advice. Requires lawyer review before publishing. Every
{{PLACEHOLDER}} must be filled in with your actual details.
-->

# Privacy Policy

**Effective date:** {{EFFECTIVE_DATE}}

This policy describes how {{COMPANY_NAME}} ("we," "us") collects, uses,
and protects information through this Friday deployment at
{{SERVICE_URL}}.

## 1. Who operates this

{{COMPANY_NAME}} ({{COMPANY_ENTITY}}) operates this instance of Friday,
an open-source business-management application. We are the data
controller for information processed through it.

## 2. What we collect

- **Account information**: email address, name, and organization
  membership. Friday is passwordless -- we never collect or store a
  password. Authentication is either a WebAuthn passkey (we store only
  the public key and a credential identifier your device gives us,
  never anything that could be used to impersonate you) or a one-time
  code emailed to you (stored only as a salted hash, never in plain
  text, and only until it's used or expires).
- **Business records you or your team enter**: whatever this
  deployment's enabled apps are used for -- CRM contacts and deals,
  invoices and customers, projects and tickets, inventory and
  purchase orders, point-of-sale transactions, and (if connected) Web3
  wallet/transaction data via Acyn Wallet.
- **Third-party integration credentials**: if your organization
  connects a third-party provider (Settings > Integrations), we store
  whatever credential that provider requires (an API key, a webhook
  URL) to make the connection work. See the connected-integrations list
  below for which ones apply to this deployment.
- **Basic technical logs**: IP address and timestamps, used only for
  rate-limiting abuse and operational troubleshooting, not profiling.

## 3. Connected third-party integrations

{{LIST ONLY THE PROVIDERS THIS DEPLOYMENT HAS ACTUALLY CONNECTED --
see Settings > Integrations. Remove every line below that doesn't
apply, and add any provider not listed here that you have connected.}}

- **Stripe** (payments) -- card payment data is handled by Stripe
  directly; we never see or store full card numbers.
- **Slack** (notifications) -- we send a notification message to a
  webhook URL you provide; no data is stored by us on Slack's side.
- **Acyn Wallet** (business wallet) -- wallet balances and transaction
  data are held by Acyn Wallet; we cache balances locally for display.
- **CoinGecko** (market data) -- public price data only, no personal
  data is sent to CoinGecko.
- **{{OTHER PROVIDER}}** -- {{WHAT IT DOES AND WHAT DATA IT SEES}}.

## 4. How we use this information

To provide the service: authenticate you, run the business workflows
this deployment is used for, and make the integrations you've connected
work. We do not sell personal information, and we do not use your
business data to train any model or for advertising.

## 5. Data retention and deletion

{{DESCRIBE YOUR ACTUAL RETENTION PERIOD AND DELETION PROCESS -- e.g.
"We retain account and business data for as long as your organization's
account is active, and delete it within N days of account closure
on request." Get this from your own policy, not from a default here.}}

## 6. Security

Data is stored in a Postgres database with row-level access control
scoping every record to your organization. Authentication is
passwordless (WebAuthn passkeys, emailed one-time codes); see
`SECURITY.md` in the Friday repository for the full technical measures
this deployment runs. {{DESCRIBE WHERE THIS IS ACTUALLY HOSTED AND ANY
ADDITIONAL MEASURES -- ENCRYPTION AT REST, BACKUP POLICY, ETC.}}

## 7. Your rights

{{DESCRIBE APPLICABLE RIGHTS FOR YOUR USERS' JURISDICTION -- e.g. GDPR
access/deletion/portability rights for EU users, CCPA rights for
California residents. This varies by where your users actually are;
get this section from your lawyer.}}

## 8. Contact

Questions about this policy: {{CONTACT_EMAIL}}.

## 9. Changes to this policy

{{DESCRIBE HOW YOU'LL NOTIFY USERS OF CHANGES.}}
