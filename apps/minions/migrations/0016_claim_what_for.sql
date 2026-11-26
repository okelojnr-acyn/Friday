-- Every spend starts somewhere (Friday Host docs/SPENDING-PLAN.md, part A):
-- what a claim was for, its category, which money paid it, and the
-- receipt's standing (a reason instead of one; the eTIMS invoice number).
ALTER TABLE expense_claims
    ADD COLUMN IF NOT EXISTS for_kind TEXT NOT NULL DEFAULT 'daily'
        CHECK (for_kind IN ('daily', 'task', 'project', 'vehicle', 'trip', 'meeting')),
    ADD COLUMN IF NOT EXISTS for_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS for_label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'other',
    ADD COLUMN IF NOT EXISTS paid_from TEXT NOT NULL DEFAULT 'own'
        CHECK (paid_from IN ('own', 'petty_cash', 'business')),
    ADD COLUMN IF NOT EXISTS no_receipt_reason TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS etims_invoice_no TEXT NOT NULL DEFAULT '';
UPDATE expense_claims SET paid_from = 'business' WHERE NOT reimburse;
