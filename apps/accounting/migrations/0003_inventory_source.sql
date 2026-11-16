-- Goods received from suppliers post from Inventory (2026-11-16):
-- Dr Inventory, Dr VAT Input, Cr Accounts Payable.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss', 'inventory'));
