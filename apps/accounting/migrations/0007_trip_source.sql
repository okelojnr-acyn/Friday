-- A settled trip (Minions, spending plan part B) books its own entry.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss', 'inventory', 'claim', 'advance', 'trip'));
