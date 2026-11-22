package auth

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"log"
	"net/http"
	"time"

	"github.com/go-webauthn/webauthn/protocol"
	"github.com/go-webauthn/webauthn/webauthn"
	"github.com/jackc/pgx/v5"
)

// Step-up checks (plan 16.4), the page half: Friday's /step-up page shows
// what the check is for and confirms it with the person's own passkey
// (the same discoverable ceremony as passkey sign-in, started with
// /auth/passkey/login-options). Guss's half is guss.StartStepUp.

func stepUpHash(code string) string {
	h := sha256.Sum256([]byte("stepup:" + code))
	return hex.EncodeToString(h[:])
}

type stepUp struct {
	id, userID, action string
	expiresAt          time.Time
	done               bool
}

func (h *Handlers) loadStepUp(r *http.Request) (stepUp, error) {
	var s stepUp
	err := h.Pool.QueryRow(r.Context(),
		`SELECT id::text, user_id::text, action, expires_at, done_at IS NOT NULL FROM core.step_ups WHERE code_hash = $1`,
		stepUpHash(r.URL.Query().Get("c"))).Scan(&s.id, &s.userID, &s.action, &s.expiresAt, &s.done)
	return s, err
}

// StepUpInfo (GET /auth/step-up?c=): what the check is for.
func (h *Handlers) StepUpInfo(w http.ResponseWriter, r *http.Request) {
	s, err := h.loadStepUp(r)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "this link isn't valid; ask Guss again")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	left := int(time.Until(s.expiresAt).Seconds())
	if left < 0 {
		left = 0
	}
	writeJSON(w, http.StatusOK, map[string]any{"action": s.action, "done": s.done, "expires_in": left})
}

// StepUpVerify (POST /auth/step-up/verify?c=&session_id=): the passkey
// answer. Only the person the check was made for can confirm it, once,
// before it expires.
func (h *Handlers) StepUpVerify(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	s, err := h.loadStepUp(r)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "this link isn't valid; ask Guss again")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if s.done {
		writeError(w, http.StatusConflict, "already confirmed; go back to the chat")
		return
	}
	if time.Now().After(s.expiresAt) {
		writeError(w, http.StatusGone, "this link has expired; ask Guss again")
		return
	}
	session, err := consumeWebauthnChallenge(ctx, h.Pool, r.URL.Query().Get("session_id"), "login")
	if err != nil {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}
	parsed, err := protocol.ParseCredentialRequestResponse(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "the browser's passkey answer couldn't be read; try again")
		return
	}
	resolveUser := func(rawID, userHandle []byte) (webauthn.User, error) {
		userID := string(userHandle)
		var email, fullName string
		if err := h.Pool.QueryRow(ctx, `SELECT email, full_name FROM core.users WHERE id = $1::uuid`, userID).Scan(&email, &fullName); err != nil {
			return nil, errors.New("unknown credential")
		}
		return loadWebauthnUser(ctx, h.Pool, userID, email, fullName)
	}
	user, cred, err := h.WebAuthn.ValidatePasskeyLogin(resolveUser, *session, parsed)
	if err != nil {
		log.Printf("step-up %s: passkey not verified: %v", s.id, err)
		writeError(w, http.StatusUnauthorized, "the passkey couldn't be verified; try again")
		return
	}
	wu, ok := user.(*webauthnUser)
	if !ok || wu.id != s.userID {
		log.Printf("step-up %s: passkey of another person offered", s.id)
		writeError(w, http.StatusForbidden, "that passkey belongs to someone else; use your own")
		return
	}
	updateWebauthnSignCount(ctx, h.Pool, cred.ID, cred.Authenticator.SignCount)
	tag, err := h.Pool.Exec(ctx,
		`UPDATE core.step_ups SET done_at = now(), method = 'passkey' WHERE id::text = $1 AND done_at IS NULL AND expires_at > now()`, s.id)
	if err != nil || tag.RowsAffected() != 1 {
		writeError(w, http.StatusConflict, "this check was already used or expired; ask Guss again")
		return
	}
	log.Printf("step-up confirmed: %s by user %s with a passkey: %q", s.id, s.userID, s.action)
	w.WriteHeader(http.StatusNoContent)
}
