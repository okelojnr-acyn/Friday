-- Who approved a till sale's price cut or big discount (roadmap item 4):
-- the team leader's or manager's email, empty when none was needed.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS override_approved_by TEXT NOT NULL DEFAULT '';
