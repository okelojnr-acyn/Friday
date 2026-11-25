-- Announcements (HR plan 8.2): to everyone, a location or a team; who it
-- went to is fixed when it's sent, so "seen by" stays true.
CREATE TABLE announcements (
    id             UUID PRIMARY KEY,
    org_id         UUID NOT NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL DEFAULT '',
    audience       TEXT NOT NULL CHECK (audience IN ('everyone', 'location', 'team')),
    location_id    UUID,
    author_user_id TEXT NOT NULL,
    author_name    TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_announcements_org ON announcements (org_id, created_at DESC);
CREATE TABLE announcement_recipients (
    announcement_id UUID NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    read_at         TIMESTAMPTZ,
    PRIMARY KEY (announcement_id, user_id)
);
CREATE INDEX idx_announcement_recipients_person ON announcement_recipients (org_id, user_id);
ALTER TABLE announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE announcements FORCE ROW LEVEL SECURITY;
CREATE POLICY announcements_org_isolation ON announcements
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
ALTER TABLE announcement_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE announcement_recipients FORCE ROW LEVEL SECURITY;
CREATE POLICY announcement_recipients_org_isolation ON announcement_recipients
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
