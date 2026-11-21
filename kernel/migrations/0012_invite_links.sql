-- Invite links (plan section 12.6, step 3): one row per invite, valid 7
-- days, used once. The link carries a random token (only its hash is
-- kept); everything the person gets on joining is decided here: role,
-- permissions, locations, who they report to.
CREATE TABLE core.invites (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    email        TEXT NOT NULL,
    full_name    TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL CHECK (role IN ('admin', 'branch_manager', 'team_leader', 'member', 'viewer')),
    perms        TEXT[] NOT NULL DEFAULT '{}',
    locations    UUID[] NOT NULL DEFAULT '{}',
    reports_to   UUID,
    token_hash   TEXT NOT NULL UNIQUE,
    invited_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL DEFAULT now() + interval '7 days',
    accepted_at  TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);
CREATE INDEX invites_org ON core.invites (org_id, created_at DESC);
CREATE INDEX invites_email ON core.invites (lower(email));
