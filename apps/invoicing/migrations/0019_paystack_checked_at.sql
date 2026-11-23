-- When Friday last asked Paystack about this sale (security/load review):
-- the till polls every few seconds, but Paystack is asked on a schedule
-- by the sale's age, claimed atomically so restarts and several workers
-- don't multiply the calls.
ALTER TABLE invoices ADD COLUMN paystack_checked_at TIMESTAMPTZ;
