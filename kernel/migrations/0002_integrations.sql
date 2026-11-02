-- Per-org third-party integration credentials (Stripe, Slack, Calendly,
-- Acyn Wallet, ...). One row per (org, provider); `config` is whatever
-- shape that provider's adapter needs (api key, webhook url, account id,
-- ...) -- see INTEGRATIONS.md for the shape each provider expects.
--
-- Stored as plain JSON, not encrypted at the column level: Friday's trust
-- boundary is already "kernel + apps share one database and one deploy"
-- (see ARCHITECTURE.md's "Trust boundary") -- the same boundary JWT_SECRET
-- and KERNEL_EVENTS_TOKEN already live inside. Securing the database
-- itself (at-rest disk encryption, restricted DB credentials) is a
-- deployment concern, same as it already is for core.users.password_hash.
CREATE TABLE core.integration_credentials (
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, provider)
);
