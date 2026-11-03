-- Passwordless auth, matching Acyn Wallet's model: WebAuthn passkeys as
-- the primary credential, emailed OTP as the only fallback -- no
-- password field, no username. core.users.password_hash is dropped;
-- every account authenticates one of these two ways from here on.

ALTER TABLE core.users DROP COLUMN password_hash;

CREATE TABLE core.webauthn_credentials (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    credential_id  TEXT NOT NULL UNIQUE,
    public_key     TEXT NOT NULL,
    sign_count     BIGINT NOT NULL DEFAULT 0,
    device_label   TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_webauthn_credentials_user ON core.webauthn_credentials(user_id);

-- One row per in-progress ceremony. `session_data` is the whole
-- go-webauthn SessionData blob (challenge + allowed credential ids +
-- expiry + relying-party user handle) JSON-serialized -- go-webauthn
-- needs the full structure back on Finish, not just the raw challenge
-- string, so this holds more than Acyn's equivalent table does.
CREATE TABLE core.webauthn_challenges (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL,
    ceremony      TEXT NOT NULL CHECK (ceremony IN ('registration', 'login')),
    session_data  JSONB NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    consumed_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_webauthn_challenges_lookup ON core.webauthn_challenges(email, ceremony, created_at DESC);

-- Emailed one-time codes -- the fallback for a device/browser that
-- can't do WebAuthn, or a user who never registered a passkey at all.
-- `payload` carries pending signup fields (org_name, full_name) through
-- to account creation on a successful 'signup' verification, the same
-- role Acyn Wallet's otpService.ts `payload` param plays.
CREATE TABLE core.otp_codes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT NOT NULL,
    purpose      TEXT NOT NULL CHECK (purpose IN ('signup', 'login')),
    code_hash    TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at   TIMESTAMPTZ NOT NULL,
    consumed_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_otp_codes_lookup ON core.otp_codes(email, purpose, created_at DESC);
