-- Tax and eTIMS settings (owner, 2026-11-16): Business settings grows a
-- Tax section (VAT registration, KRA PIN, the rates a business uses,
-- what the receipt shows) and an eTIMS section (KRA's electronic tax
-- invoice system).
--
-- tax_profile holds what any member's screens may read (the receipt
-- prints the PIN). eTIMS lives in its own table because the CMC key is a
-- credential: only owners and admins read the row, and the key itself is
-- never sent back to a browser (the API answers cmc_key_set instead).
ALTER TABLE core.orgs ADD COLUMN tax_profile JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE core.org_etims (
    org_id        UUID PRIMARY KEY REFERENCES core.orgs(id) ON DELETE CASCADE,
    enabled       BOOLEAN NOT NULL DEFAULT false,
    environment   TEXT NOT NULL DEFAULT 'sandbox' CHECK (environment IN ('sandbox', 'production')),
    mode          TEXT NOT NULL DEFAULT 'oscu' CHECK (mode IN ('oscu', 'vscu')),
    branch_id     TEXT NOT NULL DEFAULT '00',
    device_serial TEXT NOT NULL DEFAULT '',
    vscu_url      TEXT NOT NULL DEFAULT '',
    cmc_key       TEXT NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
