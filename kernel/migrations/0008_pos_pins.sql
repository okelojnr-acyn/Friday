-- Cashier PIN (plan section 11, 2026-11-16): a till-level fallback for a
-- device with no working fingerprint or face sign-in. A PIN works only on
-- a till a manager enrolled, and gives a POS-only session.

-- A trusted till. The device keeps a random token; only its SHA-256 is
-- stored here.
CREATE TABLE core.pos_devices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_by    UUID REFERENCES core.users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);
CREATE INDEX idx_pos_devices_org ON core.pos_devices(org_id);

-- One PIN per person per org, argon2id with its own salt. Five wrong
-- tries lock it for 15 minutes or until a manager unlocks it.
CREATE TABLE core.pos_pins (
    org_id        UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    salt          BYTEA NOT NULL,
    hash          BYTEA NOT NULL,
    failed        INTEGER NOT NULL DEFAULT 0,
    locked_until  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

-- Every PIN sign-in, wrong PIN and lockout, for the managers' activity
-- view. Kept 90 days.
CREATE TABLE core.pos_pin_events (
    id          BIGSERIAL PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES core.users(id) ON DELETE SET NULL,
    device_id   UUID REFERENCES core.pos_devices(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('signin', 'wrong_pin', 'locked', 'unlocked', 'pin_set', 'pin_cleared', 'device_enrolled', 'device_revoked')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pos_pin_events_org ON core.pos_pin_events(org_id, created_at DESC);
