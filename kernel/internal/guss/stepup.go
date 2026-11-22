package guss

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Step-up checks (plan 16.4): Guss asks for one before a sensitive action;
// the person confirms on Friday's /step-up page with their own passkey
// (auth.StepUpVerify). Guss then asks whether it's done.

const stepUpTTL = 5 * time.Minute

// StartStepUp (POST /guss/svc/step-up): {"telegram_id", "action"} ->
// {"id", "link", "expires_in"}; 409 if the person has no passkey yet.
func (h *Handlers) StartStepUp(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	var body struct {
		TelegramID int64  `json:"telegram_id"`
		UserID     string `json:"user_id"`
		Action     string `json:"action"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil ||
		(body.TelegramID == 0 && body.UserID == "") || strings.TrimSpace(body.Action) == "" {
		writeError(w, http.StatusBadRequest, `send {"telegram_id": 123, "action": "Void #12 ..."}`)
		return
	}
	ctx := r.Context()
	var userID string
	var err error
	if body.TelegramID != 0 {
		err = h.Pool.QueryRow(ctx, `SELECT user_id::text FROM core.guss_links WHERE org_id = $1 AND telegram_id = $2`,
			org, body.TelegramID).Scan(&userID)
	} else {
		err = h.Pool.QueryRow(ctx, `SELECT user_id::text FROM core.memberships WHERE org_id = $1 AND user_id::text = $2`,
			org, body.UserID).Scan(&userID)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "not linked")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't look up the person")
		return
	}
	var passkeys int
	h.Pool.QueryRow(ctx, `SELECT count(*) FROM core.webauthn_credentials WHERE user_id::text = $1`, userID).Scan(&passkeys)
	if passkeys == 0 {
		writeError(w, http.StatusConflict, "set up a passkey in Friday first (your profile, Passkeys)")
		return
	}
	b := make([]byte, 18)
	if _, err := rand.Read(b); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make a code")
		return
	}
	code := base64.RawURLEncoding.EncodeToString(b)
	action := strings.TrimSpace(body.Action)
	if len(action) > 300 {
		action = action[:300]
	}
	var id string
	if err := h.Pool.QueryRow(ctx,
		`INSERT INTO core.step_ups (org_id, user_id, action, code_hash, expires_at)
		 VALUES ($1, $2::uuid, $3, $4, now() + $5::interval) RETURNING id::text`,
		org, userID, action, sha("stepup:"+code), "5 minutes").Scan(&id); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the check")
		return
	}
	log.Printf("step-up asked: org %s, user %s, %q", org, userID, action)
	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "link": strings.TrimRight(h.WebURL, "/") + "/step-up?c=" + code, "expires_in": int(stepUpTTL.Seconds()),
	})
}

// StepUpStatus (GET /guss/svc/step-up/{id}): {"done": bool}, for this
// service key's org only.
func (h *Handlers) StepUpStatus(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	var done bool
	err := h.Pool.QueryRow(r.Context(),
		`SELECT done_at IS NOT NULL FROM core.step_ups WHERE id::text = $1 AND org_id = $2`, r.PathValue("id"), org).Scan(&done)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "no such check")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load the check")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"done": done})
}
