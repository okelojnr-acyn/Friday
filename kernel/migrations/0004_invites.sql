-- Widens otp_codes.purpose to support invited-member signup, which
-- reuses the exact same emailed-one-time-code machinery as a brand new
-- signup -- the only difference is what AcceptInvite does with the
-- payload (join an existing org instead of creating a new one). See
-- internal/auth/invites.go.
ALTER TABLE core.otp_codes DROP CONSTRAINT otp_codes_purpose_check;
ALTER TABLE core.otp_codes ADD CONSTRAINT otp_codes_purpose_check
    CHECK (purpose IN ('signup', 'login', 'invite'));
