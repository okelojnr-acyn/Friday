package auth

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/go-webauthn/webauthn/webauthn"
	"github.com/jackc/pgx/v5"
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

// errNoKernelAccount: the token is valid but names nobody in core.users,
// neither by id nor (within the token's org) by email. Happens with a
// Friday Host SSO token for someone the install doesn't know.
var errNoKernelAccount = errors.New("this sign-in isn't linked to a Friday account on this install -- ask an admin to invite your email, then sign in with the emailed code")

// errCredentialTaken: the authenticator returned a credential id that is
// already registered to a different account.
var errCredentialTaken = errors.New("this device's sign-in already belongs to another account -- that person should use Scan to clock in, or remove it from their account first")

// resolveWebauthnUser finds the core.users row a passkey ceremony is for.
// Normally that's the token's subject. A Friday Host SSO token
// (friday-cloud-labs api/internal/installs.MintSSO) carries the Friday
// Host user id instead, which has no row here; the email claim, signed
// with this kernel's own secret, then finds the same person, but only
// if they belong to the token's org. Without this, the credential insert
// failed on its user_id foreign key and the browser saw "db error"
// (owner report, 2026-11-15).
func resolveWebauthnUser(ctx context.Context, pool *pgxpool.Pool, claims *Claims) (*webauthnUser, error) {
	var id, email, fullName string
	err := pool.QueryRow(ctx, `
		SELECT id::text, email, full_name FROM core.users WHERE id::text = $1
	`, claims.Subject).Scan(&id, &email, &fullName)
	if errors.Is(err, pgx.ErrNoRows) && claims.Email != "" && claims.OrgID != "" {
		err = pool.QueryRow(ctx, `
			SELECT u.id::text, u.email, u.full_name
			FROM core.users u JOIN core.memberships m ON m.user_id = u.id
			WHERE lower(u.email) = lower($1) AND m.org_id::text = $2
		`, strings.TrimSpace(claims.Email), claims.OrgID).Scan(&id, &email, &fullName)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, errNoKernelAccount
	}
	if err != nil {
		return nil, err
	}
	// The authenticator shows these; an account made at the till may
	// have no full name yet.
	if fullName == "" {
		fullName = email
	}
	return loadWebauthnUser(ctx, pool, id, email, fullName)
}

// storeWebauthnCredential saves a new passkey. Registering the same
// credential again for the same person (a retried ceremony, or Windows
// Hello re-enrolling after a PIN change) refreshes the row instead of
// failing on the UNIQUE credential_id; the same id for someone else is
// errCredentialTaken.
func storeWebauthnCredential(ctx context.Context, pool *pgxpool.Pool, userID string, cred *webauthn.Credential, deviceLabel string) error {
	var id string
	err := pool.QueryRow(ctx, `
		INSERT INTO core.webauthn_credentials (user_id, credential_id, public_key, sign_count, device_label)
		VALUES ($1, $2, $3, $4, $5)
		ON CONFLICT (credential_id) DO UPDATE
			SET public_key = EXCLUDED.public_key, sign_count = EXCLUDED.sign_count,
			    device_label = CASE WHEN EXCLUDED.device_label = '' THEN core.webauthn_credentials.device_label ELSE EXCLUDED.device_label END
			WHERE core.webauthn_credentials.user_id = EXCLUDED.user_id
		RETURNING id
	`,
		userID,
		base64.RawURLEncoding.EncodeToString(cred.ID),
		base64.RawURLEncoding.EncodeToString(cred.PublicKey),
		int64(cred.Authenticator.SignCount),
		deviceLabel,
	).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return errCredentialTaken
	}
	return err
}

func updateWebauthnSignCount(ctx context.Context, pool *pgxpool.Pool, credentialID []byte, signCount uint32) error {
	_, err := pool.Exec(ctx, `
		UPDATE core.webauthn_credentials SET sign_count = $1 WHERE credential_id = $2
	`, signCount, base64.RawURLEncoding.EncodeToString(credentialID))
	return err
}
