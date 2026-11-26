-- Spending plan part D: a spend for a customer can be charged on to them
-- (billable). Their next invoice offers it; once added, it carries that
-- invoice so it's never charged twice.
ALTER TABLE expense_claims
    ADD COLUMN IF NOT EXISTS billable BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS customer_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS customer_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS billed_invoice_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_expense_claims_billable ON expense_claims (org_id, customer_id) WHERE billable AND billed_invoice_id = '';
