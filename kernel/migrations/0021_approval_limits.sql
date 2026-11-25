-- Approval limits per business (HR plan phase 1): the most a team leader
-- or branch manager may approve on one request, in the business's cents.
-- '{}' means the defaults (2,000 and 20,000).
ALTER TABLE core.orgs ADD COLUMN IF NOT EXISTS approval_limits JSONB NOT NULL DEFAULT '{}'::jsonb;
