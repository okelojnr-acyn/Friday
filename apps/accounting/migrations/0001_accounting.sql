CREATE TABLE accounts (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL CHECK (type IN ('asset', 'liability', 'equity', 'income', 'expense')),
    parent_id  UUID REFERENCES accounts(id) ON DELETE SET NULL,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accounts_org ON accounts(org_id);
-- One (org_id, code) per account -- lets _ensure_default_accounts (see
-- main.py) upsert the default Chart of Accounts idempotently.
CREATE UNIQUE INDEX idx_accounts_org_code ON accounts(org_id, code);
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY accounts_org_isolation ON accounts
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE journal_entries (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    number     TEXT NOT NULL,
    entry_date DATE NOT NULL,
    memo       TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll')),
    source_ref TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_journal_entries_org ON journal_entries(org_id);
CREATE INDEX idx_journal_entries_org_date ON journal_entries(org_id, entry_date);
ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY journal_entries_org_isolation ON journal_entries
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE journal_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL,
    journal_entry_id UUID NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    debit_cents      BIGINT NOT NULL DEFAULT 0,
    credit_cents     BIGINT NOT NULL DEFAULT 0,
    description      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_journal_lines_entry ON journal_lines(journal_entry_id);
CREATE INDEX idx_journal_lines_account ON journal_lines(account_id);
ALTER TABLE journal_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY journal_lines_org_isolation ON journal_lines
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE fiscal_periods (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    name       TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed'))
);
CREATE INDEX idx_fiscal_periods_org ON fiscal_periods(org_id);
ALTER TABLE fiscal_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE fiscal_periods FORCE ROW LEVEL SECURITY;
CREATE POLICY fiscal_periods_org_isolation ON fiscal_periods
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE bank_accounts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID NOT NULL,
    name               TEXT NOT NULL,
    account_id         UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    currency           TEXT NOT NULL DEFAULT 'USD',
    external_reference TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_bank_accounts_org ON bank_accounts(org_id);
ALTER TABLE bank_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY bank_accounts_org_isolation ON bank_accounts
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE bank_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    bank_account_id UUID NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    txn_date        DATE NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    amount_cents    BIGINT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched', 'matched'))
);
CREATE INDEX idx_bank_transactions_account ON bank_transactions(bank_account_id);
ALTER TABLE bank_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY bank_transactions_org_isolation ON bank_transactions
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
