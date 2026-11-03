package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	otpTTL         = 10 * time.Minute
	otpCooldown    = 60 * time.Second
	otpMaxAttempts = 5
)

// OtpStore is the emailed-one-time-code fallback -- the only way into an
// account that isn't a passkey ceremony, matching Acyn Wallet's model
// (see api/src/services/otpService.ts there: same 6-digit code, same
// request cooldown, same attempt cap, same salted-hash-not-plaintext
// storage).
type OtpStore struct {
	Pool *pgxpool.Pool
}

func hashOtp(email, code string) string {
	sum := sha256.Sum256([]byte(strings.ToLower(email) + ":" + code))
	return hex.EncodeToString(sum[:])
}

func generateOtpCode() (string, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}

// Request generates and stores a code, returning it for the caller to
// email -- this package has no opinion on whether an email actually
// gets sent (the "don't leak whether this email has an account" decision
// belongs in handlers.go, not here).
func (s *OtpStore) Request(ctx context.Context, email, purpose string, payload map[string]any) (string, error) {
	email = strings.ToLower(strings.TrimSpace(email))

	var recentAt time.Time
	err := s.Pool.QueryRow(ctx, `
		SELECT created_at FROM core.otp_codes WHERE email = $1 AND purpose = $2 ORDER BY created_at DESC LIMIT 1
	`, email, purpose).Scan(&recentAt)
	if err != nil && err != pgx.ErrNoRows {
		return "", err
	}
	if err == nil && time.Since(recentAt) < otpCooldown {
		return "", errors.New("a code was already sent recently -- wait a moment before requesting another")
	}

	code, err := generateOtpCode()
	if err != nil {
		return "", err
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}

	if _, err := s.Pool.Exec(ctx, `
		INSERT INTO core.otp_codes (email, purpose, code_hash, payload, expires_at)
		VALUES ($1, $2, $3, $4, $5)
	`, email, purpose, hashOtp(email, code), payloadJSON, time.Now().Add(otpTTL)); err != nil {
		return "", err
	}
	return code, nil
}

// Verify consumes the most recent unconsumed code for (email, purpose)
// and returns its stored payload (for 'signup', the pending
// org_name/full_name a successful verification creates the account
// with).
func (s *OtpStore) Verify(ctx context.Context, email, purpose, code string) (map[string]any, error) {
	email = strings.ToLower(strings.TrimSpace(email))

	var id, codeHash string
	var attempts int
	var expiresAt time.Time
	var consumedAt *time.Time
	var payloadRaw []byte

	err := s.Pool.QueryRow(ctx, `
		SELECT id, code_hash, attempts, expires_at, consumed_at, payload
		FROM core.otp_codes WHERE email = $1 AND purpose = $2 ORDER BY created_at DESC LIMIT 1
	`, email, purpose).Scan(&id, &codeHash, &attempts, &expiresAt, &consumedAt, &payloadRaw)
	if err != nil {
		return nil, errors.New("invalid or expired code")
	}
	if consumedAt != nil || time.Now().After(expiresAt) {
		return nil, errors.New("invalid or expired code")
	}
	if attempts >= otpMaxAttempts {
		return nil, errors.New("too many attempts -- request a new code")
	}
	if hashOtp(email, code) != codeHash {
		_, _ = s.Pool.Exec(ctx, `UPDATE core.otp_codes SET attempts = attempts + 1 WHERE id = $1`, id)
		return nil, errors.New("invalid or expired code")
	}

	if _, err := s.Pool.Exec(ctx, `UPDATE core.otp_codes SET consumed_at = now() WHERE id = $1`, id); err != nil {
		return nil, err
	}

	var payload map[string]any
	if len(payloadRaw) > 0 {
		_ = json.Unmarshal(payloadRaw, &payload)
	}
	return payload, nil
}
