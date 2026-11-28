-- Payment correctness (2026-11-28).
-- The Pesapal order a till sale is waiting on, so the till's status poll
-- can ask Pesapal when the IPN is late or lost.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pesapal_tracking_id TEXT NOT NULL DEFAULT '';

-- The IPN id Pesapal gave for this Friday's address, per business and
-- Pesapal account (a hash of the consumer key), so a restart or another
-- worker reuses it instead of registering the URL again.
CREATE TABLE pesapal_ipns (
    org_id     UUID NOT NULL,
    account    TEXT NOT NULL,
    url        TEXT NOT NULL,
    ipn_id     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, account, url)
);
ALTER TABLE pesapal_ipns ENABLE ROW LEVEL SECURITY;
ALTER TABLE pesapal_ipns FORCE ROW LEVEL SECURITY;
CREATE POLICY pesapal_ipns_org_isolation ON pesapal_ipns
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- When Friday last asked Paystack about a pay link Guss sent: Guss asks
-- often for 14 days, Paystack is asked at most once a minute for the
-- first hour, then every 15 minutes (claimed atomically, like
-- invoices.paystack_checked_at).
CREATE TABLE paystack_link_checks (
    org_id           UUID NOT NULL,
    reference        TEXT NOT NULL,
    first_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, reference)
);
ALTER TABLE paystack_link_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE paystack_link_checks FORCE ROW LEVEL SECURITY;
CREATE POLICY paystack_link_checks_org_isolation ON paystack_link_checks
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
