package guss

// Guss acting inside Friday: the org decides which apps Guss may read or
// write, gives Guss a service key, and each person links their Telegram
// to their Friday account. Guss then trades its key for a short-lived
// token *for that person* (their own Friday role, limited to the apps the
// org allowed; see auth.Claims.Via and gateway.EnforceAccess), so Friday's
// chain of command applies to everything done through Guss.

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math/big"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Levels an org can give Guss per app.
var accessLevels = map[string]bool{"none": true, "read": true, "write": true}

const (
	// 30 minutes: people get the code on their phone and then have to find
	// Friday on a computer (owner, 2026-11-22: 10 minutes ran out).
	linkCodeTTL = 30 * time.Minute
	// Guss asks for a fresh token per conversation turn; short on purpose.
	assistantTokenTTL = 10 * time.Minute
	serviceKeyPrefix  = "fgs_"
)

func sha(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

func randomHex(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// ServiceKey is "fgs_<org uuid>_<secret>"; only sha256(secret) is stored.
func parseServiceKey(key string) (orgID, secret string, ok bool) {
	rest, found := strings.CutPrefix(key, serviceKeyPrefix)
	if !found {
		return "", "", false
	}
	orgID, secret, found = strings.Cut(rest, "_")
	if !found || len(orgID) != 36 || len(secret) < 32 {
		return "", "", false
	}
	return orgID, secret, true
}

// ValidAccess checks an access matrix: known levels only, app names in
// the org's installed apps.
func ValidAccess(access map[string]string, installed []string) error {
	known := map[string]bool{}
	for _, a := range installed {
		known[a] = true
	}
	for app, level := range access {
		if !accessLevels[level] {
			return fmt.Errorf("%s: access must be none, read or write", app)
		}
		if !known[app] {
			return fmt.Errorf("%s isn't an installed app", app)
		}
	}
	return nil
}

// GussRole maps a Friday role onto Guss's chain of command. Viewers can't
// use Guss (it records entries).
func GussRole(fridayRole string) string {
	switch fridayRole {
	case "owner":
		return "owner"
	case "admin", "branch_manager":
		return "manager"
	// Team leaders stay "staff" here so an older Guss keeps them; a newer
	// Guss reads role "team_leader" and reports_to for their team's approvals.
	case "team_leader", "member":
		return "staff"
	default:
		return ""
	}
}

func (h *Handlers) installedApps(ctx context.Context, orgID string) ([]string, error) {
	rows, err := h.Pool.Query(ctx, `SELECT app_name FROM core.app_installs WHERE org_id = $1 ORDER BY app_name`, orgID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var apps []string
	for rows.Next() {
		var a string
		if err := rows.Scan(&a); err != nil {
			return nil, err
		}
		apps = append(apps, a)
	}
	return apps, rows.Err()
}

func (h *Handlers) loadAccess(ctx context.Context, orgID string) (map[string]string, bool, error) {
	var raw []byte
	var hasKey bool
	err := h.Pool.QueryRow(ctx,
		`SELECT access, token_hash IS NOT NULL FROM core.guss_service WHERE org_id = $1`, orgID).Scan(&raw, &hasKey)
	if errors.Is(err, pgx.ErrNoRows) {
		return map[string]string{}, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	access := map[string]string{}
	if err := json.Unmarshal(raw, &access); err != nil {
		return nil, false, err
	}
	return access, hasKey, nil
}

type linkView struct {
	TelegramID   int64  `json:"telegram_id"`
	TelegramName string `json:"telegram_name"`
	UserID       string `json:"user_id"`
	Email        string `json:"email"`
	Role         string `json:"role"`
	GussRole     string `json:"guss_role"`
	// Who they report to (a Friday user id, "" if nobody): Guss sends a
	// team leader their team's requests.
	ReportsTo string `json:"reports_to"`
}

func (h *Handlers) links(ctx context.Context, orgID, onlyUser string) ([]linkView, error) {
	q := `SELECT l.telegram_id, l.telegram_name, l.user_id, u.email, m.role, COALESCE(m.reports_to::text, '')
	      FROM core.guss_links l
	      JOIN core.users u ON u.id = l.user_id
	      JOIN core.memberships m ON m.org_id = l.org_id AND m.user_id = l.user_id
	      WHERE l.org_id = $1 AND ($2 = '' OR l.user_id::text = $2)
	      ORDER BY l.created_at`
	rows, err := h.Pool.Query(ctx, q, orgID, onlyUser)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []linkView{}
	for rows.Next() {
		var v linkView
		if err := rows.Scan(&v.TelegramID, &v.TelegramName, &v.UserID, &v.Email, &v.Role, &v.ReportsTo); err != nil {
			return nil, err
		}
		v.GussRole = GussRole(v.Role)
		out = append(out, v)
	}
	return out, rows.Err()
}

func isAdmin(c *auth.Claims) bool { return c.Role == "owner" || c.Role == "admin" }

// Access (GET /guss/access): what Guss may do here, whether it has a
// key, and the linked people (admins see everyone, others themselves).
func (h *Handlers) Access(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	ctx := r.Context()
	access, hasKey, err := h.loadAccess(ctx, c.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load Guss access")
		return
	}
	apps, err := h.installedApps(ctx, c.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load apps")
		return
	}
	only := c.Subject
	if isAdmin(c) {
		only = ""
	}
	people, err := h.links(ctx, c.OrgID, only)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load linked people")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"access": access, "apps": apps, "has_service_key": hasKey, "links": people, "bot_username": botUsername(r, h, c.OrgID),
	})
}

// SetAccess (PUT /guss/access, admins): {"access": {"inventory": "write", ...}}.
func (h *Handlers) SetAccess(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	if !isAdmin(c) {
		writeError(w, http.StatusForbidden, "only owners and admins can change Guss's access")
		return
	}
	var body struct {
		Access map[string]string `json:"access"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&body); err != nil || body.Access == nil {
		writeError(w, http.StatusBadRequest, `send {"access": {"<app>": "none|read|write"}}`)
		return
	}
	apps, err := h.installedApps(r.Context(), c.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load apps")
		return
	}
	if err := ValidAccess(body.Access, apps); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	raw, _ := json.Marshal(body.Access)
	_, err = h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_service (org_id, access) VALUES ($1, $2)
		 ON CONFLICT (org_id) DO UPDATE SET access = EXCLUDED.access, updated_at = now()`, c.OrgID, raw)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save Guss access")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"access": body.Access})
}

// NewServiceKey (POST /guss/service-key, admins): a new key for Guss,
// shown once; the old one stops working.
func (h *Handlers) NewServiceKey(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	if !isAdmin(c) {
		writeError(w, http.StatusForbidden, "only owners and admins can create Guss's key")
		return
	}
	secret, err := randomHex(24)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't create a key")
		return
	}
	_, err = h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_service (org_id, token_hash) VALUES ($1, $2)
		 ON CONFLICT (org_id) DO UPDATE SET token_hash = EXCLUDED.token_hash, updated_at = now()`, c.OrgID, sha(secret))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't save the key")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"key": serviceKeyPrefix + c.OrgID + "_" + secret})
}

// Link (POST /guss/link): {"code": "123456"} from Guss's /link links the
// caller's Friday account to that Telegram user.
func (h *Handlers) Link(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	var body struct {
		Code string `json:"code"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, `send {"code": "123456"}`)
		return
	}
	// "123 456", "123-456": only the digits count.
	code := strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, body.Code)
	var tgID int64
	var tgName string
	err := h.Pool.QueryRow(r.Context(),
		`DELETE FROM core.guss_link_codes WHERE code_hash = $1 AND org_id = $2 AND expires_at > now()
		 RETURNING telegram_id, telegram_name`, sha(c.OrgID+":"+code), c.OrgID).Scan(&tgID, &tgName)
	if errors.Is(err, pgx.ErrNoRows) {
		// Say which: a typo, or a code that ran out (codes are kept).
		var expired bool
		h.Pool.QueryRow(r.Context(), `SELECT EXISTS(SELECT 1 FROM core.guss_link_codes WHERE code_hash = $1 AND org_id = $2)`,
			sha(c.OrgID+":"+code), c.OrgID).Scan(&expired)
		log.Printf("guss link: no open code for org %s (expired: %v, digits: %d)", c.OrgID, expired, len(code))
		if expired {
			writeError(w, http.StatusGone, "that code has expired; send /link to Guss for a new one (codes last 30 minutes)")
			return
		}
		writeError(w, http.StatusNotFound, "that code doesn't match; check the 6 digits Guss sent, or send /link for a new one")
		return
	}
	if err != nil {
		log.Printf("guss link: checking the code for org %s: %v", c.OrgID, err)
		writeError(w, http.StatusInternalServerError, "couldn't check the code")
		return
	}
	_, err = h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_links (org_id, telegram_id, telegram_name, user_id) VALUES ($1, $2, $3, $4)
		 ON CONFLICT (org_id, telegram_id) DO UPDATE SET user_id = EXCLUDED.user_id, telegram_name = EXCLUDED.telegram_name`,
		c.OrgID, tgID, tgName, c.Subject)
	if err != nil {
		log.Printf("guss link: saving the link for org %s, user %s: %v", c.OrgID, c.Subject, err)
		writeError(w, http.StatusInternalServerError, "couldn't save the link")
		return
	}
	log.Printf("guss linked: org %s, telegram %d, user %s", c.OrgID, tgID, c.Subject)
	writeJSON(w, http.StatusOK, map[string]any{"telegram_id": tgID, "telegram_name": tgName})
}

// Unlink (DELETE /guss/links/{telegram_id}): admins, or the person
// themselves. Entries they made stay in Guss under their name.
func (h *Handlers) Unlink(w http.ResponseWriter, r *http.Request) {
	c, _ := auth.FromContext(r.Context())
	tgID, err := strconv.ParseInt(r.PathValue("telegram_id"), 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "telegram_id must be a number")
		return
	}
	q := `DELETE FROM core.guss_links WHERE org_id = $1 AND telegram_id = $2`
	args := []any{c.OrgID, tgID}
	if !isAdmin(c) {
		q += ` AND user_id = $3`
		args = append(args, c.Subject)
	}
	tag, err := h.Pool.Exec(r.Context(), q, args...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't unlink")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no such link")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// --- Called by Guss with its service key ---

// Service verifies Guss's key and returns the org it belongs to.
func (h *Handlers) service(r *http.Request) (string, bool) {
	key, found := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
	if !found {
		return "", false
	}
	orgID, secret, ok := parseServiceKey(key)
	if !ok {
		return "", false
	}
	var stored string
	err := h.Pool.QueryRow(r.Context(),
		`SELECT token_hash FROM core.guss_service WHERE org_id = $1 AND token_hash IS NOT NULL`, orgID).Scan(&stored)
	if err != nil {
		return "", false
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(sha(secret))) != 1 {
		return "", false
	}
	return orgID, true
}

func (h *Handlers) requireService(w http.ResponseWriter, r *http.Request) (string, bool) {
	org, ok := h.service(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "invalid Guss service key")
	}
	return org, ok
}

// LinkCode (POST /guss/svc/link-code): {"telegram_id", "name"} -> a
// 6-digit code the person enters in Friday within 10 minutes.
func (h *Handlers) LinkCode(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	var body struct {
		TelegramID int64  `json:"telegram_id"`
		Name       string `json:"name"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil || body.TelegramID == 0 {
		writeError(w, http.StatusBadRequest, `send {"telegram_id": 123, "name": "..."}`)
		return
	}
	n, err := rand.Int(rand.Reader, big.NewInt(1_000_000))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't create a code")
		return
	}
	code := fmt.Sprintf("%06d", n.Int64())
	_, err = h.Pool.Exec(r.Context(),
		`INSERT INTO core.guss_link_codes (code_hash, org_id, telegram_id, telegram_name, expires_at)
		 VALUES ($1, $2, $3, $4, now() + $5::interval)
		 ON CONFLICT (code_hash) DO UPDATE SET telegram_id = EXCLUDED.telegram_id,
		   telegram_name = EXCLUDED.telegram_name, expires_at = EXCLUDED.expires_at`,
		sha(org+":"+code), org, body.TelegramID, body.Name, fmt.Sprintf("%d seconds", int(linkCodeTTL.Seconds())))
	if err != nil {
		log.Printf("guss link code for org %s, telegram %d: save failed: %v", org, body.TelegramID, err)
		writeError(w, http.StatusInternalServerError, "couldn't save the code")
		return
	}
	log.Printf("guss link code issued: org %s, telegram %d", org, body.TelegramID)
	writeJSON(w, http.StatusOK, map[string]any{"code": code, "expires_in": int(linkCodeTTL.Seconds())})
}

// Token (POST /guss/svc/token): {"telegram_id"} -> a short-lived token
// for the linked Friday user, limited to the apps the org allowed.
func (h *Handlers) Token(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	// A Telegram person (linked with /link), or a Friday user who typed
	// into the Guss widget in Friday (actor "friday:<user id>"): their
	// entries reach Friday as them. Either way only within the service
	// key's own org.
	var body struct {
		TelegramID int64  `json:"telegram_id"`
		UserID     string `json:"user_id"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(&body); err != nil ||
		(body.TelegramID == 0 && body.UserID == "") {
		writeError(w, http.StatusBadRequest, `send {"telegram_id": 123} or {"user_id": "..."}`)
		return
	}
	var userID, email, role, name string
	var err error
	if body.TelegramID != 0 {
		err = h.Pool.QueryRow(r.Context(),
			`SELECT u.id, u.email, m.role, COALESCE(NULLIF(u.full_name, ''), l.telegram_name)
			 FROM core.guss_links l
			 JOIN core.users u ON u.id = l.user_id
			 JOIN core.memberships m ON m.org_id = l.org_id AND m.user_id = l.user_id
			 WHERE l.org_id = $1 AND l.telegram_id = $2`, org, body.TelegramID).Scan(&userID, &email, &role, &name)
	} else {
		err = h.Pool.QueryRow(r.Context(),
			`SELECT u.id, u.email, m.role, COALESCE(NULLIF(u.full_name, ''), u.email)
			 FROM core.memberships m
			 JOIN core.users u ON u.id = m.user_id
			 WHERE m.org_id = $1 AND m.user_id::text = $2`, org, body.UserID).Scan(&userID, &email, &role, &name)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "not linked")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't look up the link")
		return
	}
	access, _, err := h.loadAccess(r.Context(), org)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load Guss access")
		return
	}
	token, err := h.Issuer.IssueVia(userID, org, role, email, "guss", access, assistantTokenTTL)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't issue a token")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"token": token, "expires_in": int(assistantTokenTTL.Seconds()),
		"role": role, "guss_role": GussRole(role), "name": name, "email": email, "access": access,
	})
}

// People (GET /guss/svc/people): every linked person and their role, so
// Guss follows Friday's chain of command without asking per message.
func (h *Handlers) People(w http.ResponseWriter, r *http.Request) {
	org, ok := h.requireService(w, r)
	if !ok {
		return
	}
	people, err := h.links(r.Context(), org, "")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load linked people")
		return
	}
	access, _, err := h.loadAccess(r.Context(), org)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load Guss access")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"people": people, "access": access})
}

// botUsername is Guss's Telegram bot, "" until Guss has reported it.
func botUsername(r *http.Request, h *Handlers, orgID string) string {
	var bot string
	h.Pool.QueryRow(r.Context(), `SELECT bot_username FROM core.guss_service WHERE org_id = $1`, orgID).Scan(&bot)
	return bot
}
