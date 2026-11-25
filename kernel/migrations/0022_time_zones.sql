-- Local time (owner, 2026-11-25): everything is stored in UTC; a business's
-- day, month and books follow its own time zone, and each person sees times
-- in theirs. '' = not known yet (set from the first owner's or admin's
-- browser); apps then use UTC.
ALTER TABLE core.orgs ADD COLUMN IF NOT EXISTS time_zone TEXT NOT NULL DEFAULT '';
ALTER TABLE core.users ADD COLUMN IF NOT EXISTS time_zone TEXT NOT NULL DEFAULT '';
