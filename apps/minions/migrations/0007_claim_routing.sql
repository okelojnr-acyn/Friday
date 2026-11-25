-- HR plan phase 1: each waiting claim names who it waits on (nearest up
-- the reporting line whose limit covers it; '' = the owners and admins),
-- a decision carries its reason, and a payout says how it was paid.
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS waiting_on_user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS waiting_on_name TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS decision_note TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS decided_by_name TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ;
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS paid_method TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS paid_reference TEXT NOT NULL DEFAULT '';
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_expense_claims_waiting ON expense_claims (org_id, waiting_on_user_id) WHERE status = 'submitted';
