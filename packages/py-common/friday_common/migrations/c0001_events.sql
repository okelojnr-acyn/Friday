-- In every app's schema (applied by friday_common.migrate before the
-- app's own migrations). Plan section 13, 2026-11-16.

-- Events this app sent: written before sending, retried until the kernel
-- has them, so a hiccup never loses a sale's stock or journal update.
CREATE TABLE IF NOT EXISTS event_outbox (
    id              UUID PRIMARY KEY,
    type            TEXT NOT NULL,
    org_id          UUID NOT NULL,
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at    TIMESTAMPTZ,
    last_error      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS event_outbox_due ON event_outbox (next_attempt_at) WHERE delivered_at IS NULL;

-- Events this app received: a retried delivery is recognised and skipped.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
