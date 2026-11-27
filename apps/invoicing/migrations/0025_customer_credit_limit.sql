-- Credit limits (roadmap item 5): the most a customer may owe on credit
-- sales. NULL or 0: no limit (as before).
ALTER TABLE customers ADD COLUMN IF NOT EXISTS credit_limit_cents BIGINT;
