-- Step-up checks (plan 16.4): before a sensitive action (a large void or
-- return), Guss sends the person a one-time link; they confirm with their
-- own passkey. Each row is also the record of it: who, what, how, when.
CREATE TABLE core.step_ups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    -- What it's for, shown on the page: "Void #12: 3 rice, 360.00 KES".
    action      TEXT NOT NULL,
    -- sha256 of the link's code; the code itself is never stored.
    code_hash   TEXT NOT NULL UNIQUE,
    via         TEXT NOT NULL DEFAULT 'guss',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    done_at     TIMESTAMPTZ,
    method      TEXT
);
CREATE INDEX step_ups_org_user ON core.step_ups (org_id, user_id, created_at);
