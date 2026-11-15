-- Guss (the shop assistant) sends cash sales, expenses and paid restocks
-- as draft journal entries for the accountant to post. source_ref is
-- "guss:<entry id>" (or "guss-void:<entry id>" for a reversal), which
-- Guss checks first so a retry never books the same entry twice.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_source_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_source_check
    CHECK (source IN ('manual', 'invoicing', 'pos', 'payroll', 'guss'));
CREATE INDEX IF NOT EXISTS idx_journal_entries_source_ref ON journal_entries (org_id, source_ref);
