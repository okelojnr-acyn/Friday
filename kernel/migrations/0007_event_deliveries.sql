-- Durable event delivery (plan section 13, 2026-11-16). The kernel used
-- to forward each event in a fire-and-forget goroutine: a subscriber
-- that was slow, restarting or down never got it, and nothing recorded
-- the loss (a sale's stock or journal entry silently missing). Now each
-- event becomes one row per subscriber, delivered and retried with
-- backoff until the subscriber accepts it.
CREATE TABLE core.event_deliveries (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL,
    type            TEXT NOT NULL,
    org_id          TEXT NOT NULL,
    payload         JSONB NOT NULL,
    app             TEXT NOT NULL,
    webhook_path    TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at    TIMESTAMPTZ,
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, app, webhook_path)
);
CREATE INDEX event_deliveries_due ON core.event_deliveries (next_attempt_at) WHERE delivered_at IS NULL;
