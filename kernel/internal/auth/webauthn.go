package auth

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/go-webauthn/webauthn/webauthn"
	"github.com/jackc/pgx/v5/pgxpool"
)

const challengeTTL = 5 * time.Minute

// NewWebAuthn builds the one WebAuthn relying-party config the kernel
// uses for every ceremony. RPID must be the bare domain (no scheme/port)
// the browser's address bar shows -- "localhost" for local dev,
// "app.example.com" in production; RPOrigins is the full origin(s) the
// frontend is actually served from.
func NewWebAuthn(rpID, rpName string, origins []string) (*webauthn.WebAuthn, error) {
	return webauthn.New(&webauthn.Config{
		RPID:          rpID,
		RPDisplayName: rpName,
		RPOrigins:     origins,
	})
}

// webauthnUser adapts a core.users row to the interface go-webauthn
// needs. WebAuthnID is the user's real database id -- stable across
// every ceremony for that account, which is what the spec requires.
type webauthnUser struct {
	id          string
	email       string
	fullName    string
	credentials []webauthn.Credential
}

func (u *webauthnUser) WebAuthnID() []byte                        { return []byte(u.id) }
func (u *webauthnUser) WebAuthnName() string                      { return u.email }
func (u *webauthnUser) WebAuthnDisplayName() string                { return u.fullName }
func (u *webauthnUser) WebAuthnCredentials() []webauthn.Credential { return u.credentials }

// loadWebauthnUser fetches a user's profile plus every passkey already
// registered to them -- BeginLogin needs the credential list to build
// `allowCredentials`; BeginRegistration needs it to build
// `excludeCredentials` (so re-registering the same authenticator is
// rejected client-side instead of silently duplicating a credential).
func loadWebauthnUser(ctx context.Context, pool *pgxpool.Pool, userID, email, fullName string) (*webauthnUser, error) {
	rows, err := pool.Query(ctx, `
		SELECT credential_id, public_key, sign_count FROM core.webauthn_credentials WHERE user_id = $1
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var creds []webauthn.Credential
	for rows.Next() {
		var credIDB64, pubKeyB64 string
		var signCount int64
		if err := rows.Scan(&credIDB64, &pubKeyB64, &signCount); err != nil {
			return nil, err
		}
		idBytes, err := base64.RawURLEncoding.DecodeString(credIDB64)
		if err != nil {
			return nil, err
		}
		pkBytes, err := base64.RawURLEncoding.DecodeString(pubKeyB64)
		if err != nil {
			return nil, err
		}
		creds = append(creds, webauthn.Credential{
			ID:            idBytes,
			PublicKey:     pkBytes,
			Authenticator: webauthn.Authenticator{SignCount: uint32(signCount)},
		})
	}
	return &webauthnUser{id: userID, email: email, fullName: fullName, credentials: creds}, nil
}

// findUserByEmail looks up just enough to start a login ceremony --
// returns ok=false for an unknown email without erroring, so the login-
// options endpoint can proceed identically either way (empty
// allowCredentials for an unknown email) rather than leaking which
// emails have accounts.
func findUserByEmail(ctx context.Context, pool *pgxpool.Pool, email string) (id, fullName string, ok bool) {
	err := pool.QueryRow(ctx, `
		SELECT id, full_name FROM core.users WHERE email = $1
	`, strings.ToLower(strings.TrimSpace(email))).Scan(&id, &fullName)
	return id, fullName, err == nil
}

// storeWebauthnChallenge persists an in-progress ceremony and returns
// its row id as an opaque session token for the client to echo back on
// Finish. Keyed by that id rather than by email: PasskeyLoginOptions'
// discoverable login flow doesn't have an email to key by at all (that's
// the point -- see its own doc comment), so both ceremonies use the same
// id-based lookup for consistency rather than two different schemes.
func storeWebauthnChallenge(ctx context.Context, pool *pgxpool.Pool, ceremony string, session *webauthn.SessionData) (sessionID string, err error) {
	data, err := json.Marshal(session)
	if err != nil {
		return "", err
	}
	err = pool.QueryRow(ctx, `
		INSERT INTO core.webauthn_challenges (email, ceremony, session_data, expires_at)
		VALUES ('', $1, $2, $3) RETURNING id
	`, ceremony, data, time.Now().Add(challengeTTL)).Scan(&sessionID)
	return sessionID, err
}

// consumeWebauthnChallenge fetches and marks-consumed the challenge for
// (sessionID, ceremony). One-time use, like Acyn Wallet's
// webauthn_challenges table -- a replayed Finish call never gets a
// second chance at the same challenge. A malformed sessionID (not a
// valid UUID) fails the same lookup query and surfaces the same generic
// error as an expired one -- nothing here distinguishes "bad input"
// from "really did expire" to the caller.
func consumeWebauthnChallenge(ctx context.Context, pool *pgxpool.Pool, sessionID, ceremony string) (*webauthn.SessionData, error) {
	var raw []byte
	var expiresAt time.Time
	var consumedAt *time.Time

	err := pool.QueryRow(ctx, `
		SELECT session_data, expires_at, consumed_at FROM core.webauthn_challenges
		WHERE id = $1 AND ceremony = $2
	`, sessionID, ceremony).Scan(&raw, &expiresAt, &consumedAt)
	if err != nil {
		return nil, errors.New("this passkey ceremony has expired -- start again")
	}
	if consumedAt != nil || time.Now().After(expiresAt) {
		return nil, errors.New("this passkey ceremony has expired -- start again")
	}
	if _, err := pool.Exec(ctx, `UPDATE core.webauthn_challenges SET consumed_at = now() WHERE id = $1`, sessionID); err != nil {
		return nil, err
	}

	var session webauthn.SessionData
	if err := json.Unmarshal(raw, &session); err != nil {
		return nil, err
	}
	return &session, nil
}

func storeWebauthnCredential(ctx context.Context, pool *pgxpool.Pool, userID string, cred *webauthn.Credential, deviceLabel string) error {
	_, err := pool.Exec(ctx, `
		INSERT INTO core.webauthn_credentials (user_id, credential_id, public_key, sign_count, device_label)
		VALUES ($1, $2, $3, $4, $5)
	`,
		userID,
		base64.RawURLEncoding.EncodeToString(cred.ID),
		base64.RawURLEncoding.EncodeToString(cred.PublicKey),
		cred.Authenticator.SignCount,
		deviceLabel,
	)
	return err
}

func updateWebauthnSignCount(ctx context.Context, pool *pgxpool.Pool, credentialID []byte, signCount uint32) error {
	_, err := pool.Exec(ctx, `
		UPDATE core.webauthn_credentials SET sign_count = $1 WHERE credential_id = $2
	`, signCount, base64.RawURLEncoding.EncodeToString(credentialID))
	return err
}
