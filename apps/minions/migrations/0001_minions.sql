CREATE TABLE employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    department      TEXT NOT NULL DEFAULT '',
    pay_rate_cents  BIGINT NOT NULL DEFAULT 0,
    pay_frequency   TEXT NOT NULL DEFAULT 'monthly' CHECK (pay_frequency IN ('weekly', 'biweekly', 'monthly')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    wallet_address  TEXT NOT NULL DEFAULT '',
    wallet_network  TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_employees_org ON employees(org_id);
CREATE INDEX idx_employees_org_user ON employees(org_id, user_id) WHERE user_id <> '';
-- Admins provision by email (the kernel has no org-member directory to
-- pick a user_id from); one employee row per (org, email), claimed by
-- user_id on first self-service access -- see main.py's
-- _resolve_my_employee.
CREATE UNIQUE INDEX idx_employees_org_email ON employees(org_id, email);
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees FORCE ROW LEVEL SECURITY;
CREATE POLICY employees_org_isolation ON employees
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE expense_claims (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    description  TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'USD',
    status       TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'approved', 'rejected', 'paid')),
    receipt_url  TEXT NOT NULL DEFAULT '',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_expense_claims_org ON expense_claims(org_id);
CREATE INDEX idx_expense_claims_employee ON expense_claims(employee_id);
ALTER TABLE expense_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE expense_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY expense_claims_org_isolation ON expense_claims
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE payroll_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    period_start  TIMESTAMPTZ NOT NULL,
    period_end    TIMESTAMPTZ NOT NULL,
    payout_method TEXT NOT NULL DEFAULT 'crypto' CHECK (payout_method IN ('crypto', 'fiat')),
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'paying', 'paid')),
    currency      TEXT NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_payroll_runs_org ON payroll_runs(org_id);
ALTER TABLE payroll_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY payroll_runs_org_isolation ON payroll_runs
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE payroll_lines (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID NOT NULL,
    payroll_run_id     UUID NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    employee_name      TEXT NOT NULL,
    gross_amount_cents BIGINT NOT NULL,
    to_address         TEXT NOT NULL DEFAULT '',
    network            TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'blocked', 'sent', 'confirmed', 'failed')),
    external_id        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_payroll_lines_run ON payroll_lines(payroll_run_id);
ALTER TABLE payroll_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY payroll_lines_org_isolation ON payroll_lines
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
