-- A business on Friday Host's shared Friday whose subscription lapsed
-- (`kernel suspend`): nobody in it can use Friday until it's paid. Its
-- data stays. NULL: active.
ALTER TABLE core.orgs ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;
