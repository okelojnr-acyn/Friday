-- The notification inbox (HR plan 8.4.1): one per person per business,
-- shown as a bell in Friday and in Minions, also sent on Guss. event_id
-- makes a retried delivery land once.
CREATE TABLE core.notifications (
    id          BIGSERIAL PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    event_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    link        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at     TIMESTAMPTZ,
    UNIQUE (event_id, user_id)
);
CREATE INDEX idx_notifications_person ON core.notifications (user_id, org_id, created_at DESC);
