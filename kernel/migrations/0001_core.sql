-- Core schema: orgs, users, memberships, and the apps catalog.
-- Every app (apps/crm, apps/invoicing, apps/projects) owns its own schema
-- and references core.orgs(id) / core.users(id) by id only -- no foreign
-- keys across schemas, so any app can be split into its own database later
-- without a migration on core.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE core.orgs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    full_name      TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.memberships (
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

-- Static catalog of apps that exist in this deployment. Rows are seeded by
-- the kernel at startup from its app registry config, not hand-edited.
CREATE TABLE core.apps (
    name         TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    icon         TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT 'other'
);

-- Which apps each org has enabled. An app existing in core.apps doesn't
-- mean every org sees it -- this is the "apps catalog" install/enable
-- toggle from the launcher.
CREATE TABLE core.app_installs (
    org_id       UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    app_name     TEXT NOT NULL REFERENCES core.apps(name) ON DELETE CASCADE,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, app_name)
);

CREATE INDEX idx_memberships_user ON core.memberships(user_id);
CREATE INDEX idx_app_installs_org ON core.app_installs(org_id);
