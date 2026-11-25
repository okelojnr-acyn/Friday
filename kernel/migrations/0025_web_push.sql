-- Phone notifications for Minions (Web Push). One VAPID key pair per
-- Friday install (the private key sealed with FRIDAY_SECRETS_KEY), and each
-- phone or browser a person turned notifications on in.
CREATE TABLE core.push_keys (
    id           INT PRIMARY KEY CHECK (id = 1),
    public_key   TEXT NOT NULL,
    private_key  BYTEA NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE core.push_subscriptions (
    id          BIGSERIAL PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    user_agent  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_push_subscriptions_person ON core.push_subscriptions (org_id, user_id);
