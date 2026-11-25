-- Cover while away (HR plan phase 3): an approver names who decides for
-- them between two dates. One at a time per person.
CREATE TABLE approval_cover (
    org_id           UUID NOT NULL,
    user_id          TEXT NOT NULL,
    delegate_user_id TEXT NOT NULL,
    delegate_name    TEXT NOT NULL DEFAULT '',
    delegate_role    TEXT NOT NULL DEFAULT '',
    starts_on        DATE NOT NULL,
    ends_on          DATE NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id),
    CHECK (ends_on >= starts_on)
);
ALTER TABLE approval_cover ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_cover FORCE ROW LEVEL SECURITY;
CREATE POLICY approval_cover_org_isolation ON approval_cover
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- Unpaid leave taken off a payslip: the days, and what they took off.
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS unpaid_days INT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS unpaid_cents BIGINT NOT NULL DEFAULT 0;
