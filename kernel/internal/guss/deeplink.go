package guss

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// One-tap Telegram linking (plan 16.2). Friday makes a code for the
// signed-in person and opens Guss with it (t.me/<bot>?start=link-<code>);
// Guss redeems it with its service key. The code is the person's own
// proof: only someone signed in to Friday can make one, and it works once,
// for 15 minutes.

const webCodeTTL = 15 * time.Minute

var botUsernameRe = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]{3,31}$`)

// SetBot (POST /guss/svc/bot): Guss reports its Telegram bot's username.
func (h *Handlers) SetBot(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	var body struct {
		Username string `json:"username"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<10)).Decode(&body); err != nil ||
		!botUsernameRe.MatchString(strings.TrimPrefix(body.Username, "@")) {
		writeError(w, http.StatusBadRequest, `send {"username": "MyShopBot"}`)
		return
	}
	if _, err := h.Pool.Exec(r.Context(),
		`UPDATE core.guss_service SET bot_username = $2, updated_at = now() WHERE org_id = $1`,
		org, strings.TrimPrefix(body.Username, "@")); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the bot")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// WebLinkCode (POST /guss/link-code): a one-time code for the signed-in
// person and the Telegram link that hands it to Guss.
func (h *Handlers) WebLinkCode(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok || c.Via != "" || c.Role == "viewer" {
		writeError(w, http.StatusForbidden, "sign in to Friday yourself to link your Telegram")
		return
	}
	var bot string
	h.Pool.QueryRow(r.Context(), `SELECT bot_username FROM core.guss_service WHERE org_id = $1`, c.OrgID).Scan(&bot)
	if bot == "" {
		writeError(w, http.StatusConflict, "Guss hasn't told Friday its Telegram bot yet; update Guss, or send /link to it")
		return
	}
	b := make([]byte, 18)
	if _, err := rand.Read(b); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make a code")
		return
	}
	code := base64.RawURLEncoding.EncodeToString(b)
	if _, err := h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_web_codes (code_hash, org_id, user_id, expires_at) VALUES ($1, $2, $3::uuid, now() + $4::interval)`,
		sha("web:"+code), c.OrgID, c.Subject, "15 minutes"); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the code")
		return
	}
	log.Printf("guss web link code issued: org %s, user %s", c.OrgID, c.Subject)
	writeJSON(w, http.StatusOK, map[string]any{
		"link": "https://t.me/" + bot + "?start=link-" + code, "bot": bot, "expires_in": int(webCodeTTL.Seconds()),
	})
}

// Redeem (POST /guss/svc/redeem): {"code", "telegram_id", "name"} from
// Guss's /start link-<code>: links that Telegram user to the person who
// made the code, once.
func (h *Handlers) Redeem(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	var body struct {
		Code       string `json:"code"`
		TelegramID int64  `json:"telegram_id"`
		Name       string `json:"name"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil || body.TelegramID == 0 || body.Code == "" {
		writeError(w, http.StatusBadRequest, `send {"code": "...", "telegram_id": 123, "name": "..."}`)
		return
	}
	var userID string
	err := h.Pool.QueryRow(r.Context(),
		`DELETE FROM core.guss_web_codes WHERE code_hash = $1 AND org_id = $2 AND expires_at > now() RETURNING user_id::text`,
		sha("web:"+body.Code), org).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		log.Printf("guss redeem: no open web code for org %s", org)
		writeError(w, http.StatusNotFound, "that link has expired or was used; press Link my Telegram in Friday again")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't check the code")
		return
	}
	if _, err := h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_links (org_id, telegram_id, telegram_name, user_id) VALUES ($1, $2, $3, $4::uuid)
		 ON CONFLICT (org_id, telegram_id) DO UPDATE SET user_id = EXCLUDED.user_id, telegram_name = EXCLUDED.telegram_name`,
		org, body.TelegramID, body.Name, userID); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the link")
		return
	}
	var email, role string
	h.Pool.QueryRow(r.Context(), `SELECT u.email, m.role FROM core.users u JOIN core.memberships m ON m.user_id = u.id AND m.org_id = $1 WHERE u.id::text = $2`,
		org, userID).Scan(&email, &role)
	log.Printf("guss linked by web code: org %s, telegram %d, user %s", org, body.TelegramID, userID)
	writeJSON(w, http.StatusOK, map[string]any{"email": email, "role": role, "guss_role": GussRole(role)})
}
