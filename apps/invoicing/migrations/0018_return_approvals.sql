-- Who approved a staff return at the till (plan 12.2): the team leader's
-- or manager's user id from their PIN approval; '' when none was needed.
ALTER TABLE invoices ADD COLUMN approved_by TEXT NOT NULL DEFAULT '';
