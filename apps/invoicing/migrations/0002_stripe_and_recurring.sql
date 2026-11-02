ALTER TABLE invoices ADD COLUMN stripe_payment_intent_id TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN recurring_interval TEXT NOT NULL DEFAULT ''
    CHECK (recurring_interval IN ('', 'weekly', 'monthly', 'yearly'));
ALTER TABLE invoices ADD COLUMN next_recurrence_at TIMESTAMPTZ;

CREATE INDEX idx_invoices_recurring_due ON invoices(org_id, next_recurrence_at)
    WHERE recurring_interval <> '';
