-- A person's role, jobs, locations or manager changed (owner, 2026-11-26:
-- the staff app kept the old jobs until the next sign-in). Tokens issued
-- before this are refused, and the app swaps them for fresh ones.
ALTER TABLE core.memberships ADD COLUMN IF NOT EXISTS access_changed_at TIMESTAMPTZ;
