-- Spending plan part D: each project's budget (0 = none), in the
-- business's money; Minions says what was spent against it.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS budget_cents BIGINT NOT NULL DEFAULT 0 CHECK (budget_cents >= 0);
