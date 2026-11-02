CREATE TABLE wallets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL,
    provider    TEXT NOT NULL DEFAULT 'acyn_wallet',
    network     TEXT NOT NULL,
    address     TEXT NOT NULL DEFAULT '',
    currency    TEXT NOT NULL DEFAULT '',
    balance     TEXT NOT NULL DEFAULT '0',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, provider, network, currency)
);

CREATE INDEX idx_wallets_org ON wallets(org_id);

CREATE TABLE transactions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('payout', 'credit_transfer')),
    external_id  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending',
    amount       TEXT NOT NULL DEFAULT '0',
    currency     TEXT NOT NULL DEFAULT '',
    network      TEXT NOT NULL DEFAULT '',
    to_address   TEXT NOT NULL DEFAULT '',
    reason       TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_transactions_org ON transactions(org_id);

-- Row-Level Security: see apps/crm/migrations for the full explanation.
ALTER TABLE wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallets FORCE ROW LEVEL SECURITY;
CREATE POLICY wallets_org_isolation ON wallets
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY transactions_org_isolation ON transactions
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
