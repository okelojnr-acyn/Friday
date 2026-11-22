-- Who paid (owner, 2026-11-22): a claim is either money the person spent
-- and wants back (reimburse), or spending the business already paid that
-- is only being recorded (no payout).
ALTER TABLE expense_claims ADD COLUMN reimburse BOOLEAN NOT NULL DEFAULT true;
