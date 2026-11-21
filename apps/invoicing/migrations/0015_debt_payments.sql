-- Credit sales and paying debts (owner's plan, Guss follow-ups, 2026-11-21).
-- A payment against a customer's debt carries the sender's own id, so a
-- payment sent twice (Guss retries) is recorded once. Several rows share
-- one id when a payment settles several sales.
ALTER TABLE payments ADD COLUMN client_ref TEXT;
CREATE INDEX idx_payments_client_ref ON payments (org_id, client_ref) WHERE client_ref IS NOT NULL;
