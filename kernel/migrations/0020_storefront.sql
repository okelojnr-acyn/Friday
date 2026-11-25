-- Online store look (Store settings): logo, colours, fonts, corners. The
-- downloadable store kit (STOREFRONT-PLAN.md) reads it as its brand tokens.
ALTER TABLE core.orgs ADD COLUMN IF NOT EXISTS storefront JSONB NOT NULL DEFAULT '{}'::jsonb;
