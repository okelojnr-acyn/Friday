-- Petty cash top-ups and counts (Minions, spending plan part C) book
-- their own entries; trips (part B, 0007) stay allowed.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss', 'inventory', 'claim', 'advance', 'trip', 'petty'));
