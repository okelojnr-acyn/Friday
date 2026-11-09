-- Meeting scheduling, synced to the org's connected Google Calendar.
-- The OAuth2 consent flow (kernel/internal/integrations/google_oauth.go)
-- and the actual API client (friday_common.integrations.
-- GoogleCalendarProvider) have existed since 2026-11-08 with nothing
-- in any app ever calling create_event -- this is the feature that
-- finally does.
CREATE TABLE meetings (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID NOT NULL,
    title              TEXT NOT NULL,
    starts_at          TIMESTAMPTZ NOT NULL,
    ends_at            TIMESTAMPTZ NOT NULL,
    attendee_emails    TEXT NOT NULL DEFAULT '',
    created_by_email   TEXT NOT NULL DEFAULT '',
    calendar_event_id  TEXT NOT NULL DEFAULT '',
    calendar_link      TEXT NOT NULL DEFAULT '',
    sync_status        VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (sync_status IN ('pending', 'synced', 'error')),
    sync_error         TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_meetings_org ON meetings(org_id);

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings FORCE ROW LEVEL SECURITY;
CREATE POLICY meetings_org_isolation ON meetings
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
