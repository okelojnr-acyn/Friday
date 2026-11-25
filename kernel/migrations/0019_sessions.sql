-- Each sign-in is a session people see under "Devices" and can sign out;
-- the token carries its id (sid) and is refused once it's revoked.
CREATE TABLE core.sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    user_agent   TEXT NOT NULL DEFAULT '',
    ip           TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ
);
CREATE INDEX idx_sessions_user ON core.sessions (user_id, created_at DESC);
