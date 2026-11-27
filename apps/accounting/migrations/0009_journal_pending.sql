-- Manual journal entries above the business's limit wait for an owner
-- (roadmap item 8): status 'pending' between draft and posted, and who
-- approved it once posted.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_status_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_status_check CHECK (status IN ('draft', 'pending', 'posted'));
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS approved_by TEXT NOT NULL DEFAULT '';
