-- Salary advances (HR plan phase 2): asked for like a claim (routed up
-- the reporting line), paid like one, and recovered from the next 1-3
-- payslips. One open at a time; at most half of one pay.
CREATE TABLE salary_advances (
    id                 UUID PRIMARY KEY,
    org_id             UUID NOT NULL,
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    description        TEXT NOT NULL DEFAULT '',
    amount_cents       BIGINT NOT NULL CHECK (amount_cents > 0),
    currency           TEXT NOT NULL DEFAULT 'KES',
    months             SMALLINT NOT NULL DEFAULT 1 CHECK (months BETWEEN 1 AND 3),
    status             TEXT NOT NULL DEFAULT 'submitted'
                       CHECK (status IN ('submitted', 'approved', 'rejected', 'paid', 'recovered', 'withdrawn')),
    waiting_on_user_id TEXT NOT NULL DEFAULT '',
    waiting_on_name    TEXT NOT NULL DEFAULT '',
    decision_note      TEXT NOT NULL DEFAULT '',
    decided_by_name    TEXT NOT NULL DEFAULT '',
    decided_at         TIMESTAMPTZ,
    paid_method        TEXT NOT NULL DEFAULT '',
    paid_reference     TEXT NOT NULL DEFAULT '',
    paid_at            TIMESTAMPTZ,
    recovered_cents    BIGINT NOT NULL DEFAULT 0,
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_salary_advances_person ON salary_advances (org_id, employee_id);
ALTER TABLE salary_advances ENABLE ROW LEVEL SECURITY;
ALTER TABLE salary_advances FORCE ROW LEVEL SECURITY;
CREATE POLICY salary_advances_org_isolation ON salary_advances
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- What a payroll line takes back towards an advance.
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS advance_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS advance_id UUID;
