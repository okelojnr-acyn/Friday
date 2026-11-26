-- The business's spending policy (Friday Host docs/SPENDING-PLAN.md):
-- {} = the Standard preset.
ALTER TABLE core.orgs ADD COLUMN IF NOT EXISTS spending_policy JSONB NOT NULL DEFAULT '{}'::jsonb;
