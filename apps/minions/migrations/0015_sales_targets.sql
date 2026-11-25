-- A standing monthly sales target per person (HR plan 8.2: team sales
-- vs target), set by whoever is over them; 0 = none.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS sales_target_cents BIGINT NOT NULL DEFAULT 0;
