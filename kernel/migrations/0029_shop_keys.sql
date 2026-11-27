-- Shop keys (internal/shop): what an online shop's page uses to read the
-- business's catalogue. Public by design (they sit in page code) and
-- read-only; origins limits which sites may use one (empty: any).
CREATE TABLE IF NOT EXISTS core.shop_keys (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    key        TEXT NOT NULL UNIQUE,
    origins    TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_shop_keys_org ON core.shop_keys(org_id);
