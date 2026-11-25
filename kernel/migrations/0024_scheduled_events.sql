-- Scheduled events (2026-11-25): an app may ask for an event to be
-- delivered at a time (a task falling due, a meeting reminder), instead
-- of anything polling. scheduled_for keeps waiting ones out of the
-- health check's pending and stuck counts until their time.
ALTER TABLE core.event_deliveries ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_event_deliveries_due ON core.event_deliveries (next_attempt_at) WHERE delivered_at IS NULL;
