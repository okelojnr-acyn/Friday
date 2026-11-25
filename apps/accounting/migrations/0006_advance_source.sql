-- Salary advances paid out (HR plan phase 2) are their own entries.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss', 'inventory', 'claim', 'advance'));
