-- One-tap Telegram linking (plan 16.2): Friday makes a one-time code for
-- the signed-in person and opens t.me/<bot>?start=link-<code>; Guss
-- redeems it. Guss tells Friday its bot's username so Friday can build
-- the link.
ALTER TABLE core.guss_service ADD COLUMN bot_username TEXT NOT NULL DEFAULT '';
CREATE TABLE core.guss_web_codes (
    code_hash   TEXT PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);
