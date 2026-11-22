-- Expense claim payouts from Minions (minions.expense_claim.paid).
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss', 'inventory', 'claim'));
