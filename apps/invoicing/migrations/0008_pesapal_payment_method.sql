-- Real bug, caught by actually running the test suite (not just syntax/
-- lint checks) once Postgres was finally reachable: 0007_pos_identity.sql
-- added "pesapal" to the Python-side PAYMENT_METHODS tuple
-- (apps/invoicing/app/models.py) but never widened this DB-level CHECK
-- constraint to match, so pesapal_webhook's own Payment insert
-- (apps/invoicing/app/webhooks.py) violated payments_method_check on
-- every real confirmation. Same drop+add pattern 0003_pos_returns.sql
-- already used to add "refund".
ALTER TABLE payments DROP CONSTRAINT payments_method_check;
ALTER TABLE payments ADD CONSTRAINT payments_method_check
    CHECK (method IN ('cash', 'card', 'pos', 'bank_transfer', 'refund', 'pesapal', 'other'));
