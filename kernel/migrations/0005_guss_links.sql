-- Guss inside Friday (see internal/guss/link.go): what Guss may do per
-- app, its service key, and which Telegram user is which Friday member.

-- One row per org. access: {"<app>": "none" | "read" | "write"}; apps not
-- listed are "none". token_hash: sha256 of the service key's secret.
CREATE TABLE core.guss_service (
    org_id      UUID PRIMARY KEY REFERENCES core.orgs(id) ON DELETE CASCADE,
    token_hash  TEXT,
    access      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A Telegram user acting as a Friday member through Guss. The member's
-- Friday role is their role in Guss (owner, admin -> manager, member ->
-- staff); removing the membership removes the link.
CREATE TABLE core.guss_links (
    org_id         UUID NOT NULL,
    telegram_id    BIGINT NOT NULL,
    telegram_name  TEXT NOT NULL DEFAULT '',
    user_id        UUID NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, telegram_id),
    FOREIGN KEY (org_id, user_id) REFERENCES core.memberships(org_id, user_id) ON DELETE CASCADE
);

-- Short-lived codes from Guss's /link, entered in Friday by the person.
CREATE TABLE core.guss_link_codes (
    code_hash      TEXT PRIMARY KEY,
    org_id         UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    telegram_id    BIGINT NOT NULL,
    telegram_name  TEXT NOT NULL DEFAULT '',
    expires_at     TIMESTAMPTZ NOT NULL
);
