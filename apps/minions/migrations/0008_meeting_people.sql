-- Meetings between people of the business (HR plan 8.4.3): who organised
-- it, and each invited member with their answer. attendee_emails stays
-- the list Google Calendar invites (members and outside guests).
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS created_by_user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS created_by_name TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS meeting_attendees (
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    org_id     UUID NOT NULL,
    user_id    TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    response   TEXT NOT NULL DEFAULT 'invited' CHECK (response IN ('invited', 'accepted', 'declined')),
    PRIMARY KEY (meeting_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_meeting_attendees_person ON meeting_attendees (org_id, user_id);
ALTER TABLE meeting_attendees ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_attendees FORCE ROW LEVEL SECURITY;
CREATE POLICY meeting_attendees_org_isolation ON meeting_attendees
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
