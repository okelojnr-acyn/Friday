-- A claim its maker takes back while it waits (owner, 2026-11-22: a
-- pay-me-back expense voided in Guss withdraws its claim).
ALTER TABLE expense_claims DROP CONSTRAINT IF EXISTS expense_claims_status_check;
ALTER TABLE expense_claims ADD CONSTRAINT expense_claims_status_check
    CHECK (status IN ('submitted', 'approved', 'rejected', 'paid', 'withdrawn'));
