package auth

// Cashier PIN (plan section 11). A fallback for a till whose fingerprint or
// face sign-in doesn't work. Three rules keep it safe:
//   - a PIN works only on a till a manager enrolled ("Trust this till");
//   - five wrong tries lock that person's PIN for 15 minutes, or until a
//     manager unlocks it;
//   - a PIN session reaches the till's apps only (Via "pos"), never admin
//     pages or settings, and never with more than the member role.

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"golang.org/x/crypto/argon2"
)

const (
	// PosVia marks a token issued from a cashier PIN.
	PosVia          = "pos"
	posPinTokenTTL  = 12 * time.Hour
	posPinMaxFailed = 5
	posPinLockFor   = 15 * time.Minute
	// PosDeviceHeader carries an enrolled till's device token.
	PosDeviceHeader = "X-Pos-Device"
)

// posAccess is what a PIN session may reach: selling and shifts live in
// Invoicing, the shelf is read from Inventory.
var posAccess = map[string]string{"invoicing": "write", "inventory": "read"}

var pinRe = regexp.MustCompile(`^[0-9]{6}$`)

// Weak PINs a till would see first in a guessing attempt.
var weakPins = map[string]bool{
	"000000": true, "111111": true, "222222": true, "333333": true, "444444": true,
	"555555": true, "666666": true, "777777": true, "888888": true, "999999": true,
	"123456": true, "654321": true, "123123": true, "121212": true,
}

func hashPin(pin string, salt []byte) []byte {
	return argon2.IDKey([]byte(pin), salt, 2, 19*1024, 1, 32)
}

func hashDeviceToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// posManager is an owner or admin on a full session (not a PIN or
// assistant token).
func posManager(w http.ResponseWriter, r *http.Request) (*Claims, bool) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return nil, false
	}
	if claims.Via != "" || (claims.Role != "owner" && claims.Role != "admin") {
		writeError(w, http.StatusForbidden, "only an owner or admin signed in with a passkey or email code can do this")
		return nil, false
	}
	return claims, true
}

func (h *Handlers) posEvent(ctx context.Context, orgID string, userID, deviceID *string, kind string) {
	h.Pool.Exec(ctx, `INSERT INTO core.pos_pin_events (org_id, user_id, device_id, kind) VALUES ($1, $2, $3, $4)`,
		orgID, userID, deviceID, kind)
}

// EnrolPosDevice trusts this till for PIN sign-in. The token is shown once.
func (h *Handlers) EnrolPosDevice(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	var req struct {
		Name string `json:"name"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	name := strings.TrimSpace(req.Name)
	if name == "" {
		name = "Till"
	}
	if len(name) > 60 {
		name = name[:60]
	}
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		writeError(w, http.StatusInternalServerError, "could not create a device token")
		return
	}
	token := base64.RawURLEncoding.EncodeToString(b)
	var id string
	if err := h.Pool.QueryRow(r.Context(), `
		INSERT INTO core.pos_devices (org_id, name, token_hash, created_by) VALUES ($1, $2, $3, $4) RETURNING id::text`,
		claims.OrgID, name, hashDeviceToken(token), claims.Subject).Scan(&id); err != nil {
		writeError(w, http.StatusInternalServerError, "could not enrol this till")
		return
	}
	h.posEvent(r.Context(), claims.OrgID, &claims.Subject, &id, "device_enrolled")
	writeJSON(w, http.StatusCreated, map[string]string{"id": id, "name": name, "token": token})
}

type posDevice struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	CreatedAt  time.Time  `json:"created_at"`
	LastUsedAt *time.Time `json:"last_used_at"`
	RevokedAt  *time.Time `json:"revoked_at"`
}

func (h *Handlers) ListPosDevices(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT id::text, name, created_at, last_used_at, revoked_at FROM core.pos_devices
		WHERE org_id = $1 ORDER BY revoked_at IS NOT NULL, created_at DESC`, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list tills")
		return
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (posDevice, error) {
		var d posDevice
		return d, row.Scan(&d.ID, &d.Name, &d.CreatedAt, &d.LastUsedAt, &d.RevokedAt)
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list tills")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (h *Handlers) RevokePosDevice(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	id := r.PathValue("id")
	tag, err := h.Pool.Exec(r.Context(), `
		UPDATE core.pos_devices SET revoked_at = now() WHERE id::text = $1 AND org_id = $2 AND revoked_at IS NULL`,
		id, claims.OrgID)
	if err != nil || tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no such till")
		return
	}
	h.posEvent(r.Context(), claims.OrgID, &claims.Subject, &id, "device_revoked")
	w.WriteHeader(http.StatusNoContent)
}

// SetPosPin sets a PIN: your own (PUT /pos/pin), or, for an owner or
// admin, someone else's in the org (PUT /pos/pins/{user_id}).
func (h *Handlers) SetPosPin(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if claims.Via != "" {
		writeError(w, http.StatusForbidden, "sign in with your fingerprint or an email code to set a PIN")
		return
	}
	userID := claims.Subject
	if other := r.PathValue("user_id"); other != "" && other != claims.Subject {
		if _, ok := posManager(w, r); !ok {
			return
		}
		userID = other
	}
	var req struct {
		Pin string `json:"pin"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	if !pinRe.MatchString(req.Pin) {
		writeError(w, http.StatusBadRequest, "a PIN is exactly 6 digits")
		return
	}
	if weakPins[req.Pin] {
		writeError(w, http.StatusBadRequest, "that PIN is too easy to guess; pick another")
		return
	}
	var member bool
	h.Pool.QueryRow(r.Context(), `SELECT EXISTS (SELECT 1 FROM core.memberships WHERE org_id = $1 AND user_id::text = $2)`,
		claims.OrgID, userID).Scan(&member)
	if !member {
		writeError(w, http.StatusNotFound, "that person isn't in this organisation")
		return
	}
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		writeError(w, http.StatusInternalServerError, "could not set the PIN")
		return
	}
	if _, err := h.Pool.Exec(r.Context(), `
		INSERT INTO core.pos_pins (org_id, user_id, salt, hash) VALUES ($1, $2::uuid, $3, $4)
		ON CONFLICT (org_id, user_id) DO UPDATE
		SET salt = EXCLUDED.salt, hash = EXCLUDED.hash, failed = 0, locked_until = NULL, updated_at = now()`,
		claims.OrgID, userID, salt, hashPin(req.Pin, salt)); err != nil {
		writeError(w, http.StatusInternalServerError, "could not set the PIN")
		return
	}
	h.posEvent(r.Context(), claims.OrgID, &userID, nil, "pin_set")
	w.WriteHeader(http.StatusNoContent)
}

// MyPosPin says whether the signed-in person has a PIN in this org.
func (h *Handlers) MyPosPin(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	var has bool
	h.Pool.QueryRow(r.Context(), `SELECT EXISTS (SELECT 1 FROM core.pos_pins WHERE org_id = $1 AND user_id::text = $2)`,
		claims.OrgID, claims.Subject).Scan(&has)
	writeJSON(w, http.StatusOK, map[string]bool{"has_pin": has})
}

type posPerson struct {
	UserID      string     `json:"user_id"`
	Name        string     `json:"name"`
	Email       string     `json:"email,omitempty"`
	Role        string     `json:"role,omitempty"`
	HasPin      bool       `json:"has_pin"`
	LockedUntil *time.Time `json:"locked_until"`
}

// ListPosPins lists the org's people and their PIN state, for managers.
func (h *Handlers) ListPosPins(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT u.id::text, u.full_name, u.email, m.role, p.user_id IS NOT NULL,
		       CASE WHEN p.locked_until > now() THEN p.locked_until END
		FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		LEFT JOIN core.pos_pins p ON p.org_id = m.org_id AND p.user_id = m.user_id
		WHERE m.org_id = $1 ORDER BY lower(coalesce(nullif(u.full_name, ''), u.email))`, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list people")
		return
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (posPerson, error) {
		var p posPerson
		return p, row.Scan(&p.UserID, &p.Name, &p.Email, &p.Role, &p.HasPin, &p.LockedUntil)
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list people")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

func (h *Handlers) UnlockPosPin(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	userID := r.PathValue("user_id")
	tag, err := h.Pool.Exec(r.Context(), `
		UPDATE core.pos_pins SET failed = 0, locked_until = NULL WHERE org_id = $1 AND user_id::text = $2`,
		claims.OrgID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "that person has no PIN")
		return
	}
	h.posEvent(r.Context(), claims.OrgID, &userID, nil, "unlocked")
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) ClearPosPin(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	userID := r.PathValue("user_id")
	tag, err := h.Pool.Exec(r.Context(), `DELETE FROM core.pos_pins WHERE org_id = $1 AND user_id::text = $2`,
		claims.OrgID, userID)
	if err != nil || tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "that person has no PIN")
		return
	}
	h.posEvent(r.Context(), claims.OrgID, &userID, nil, "pin_cleared")
	w.WriteHeader(http.StatusNoContent)
}

type posPinEvent struct {
	Kind      string    `json:"kind"`
	Name      string    `json:"name"`
	Device    string    `json:"device"`
	CreatedAt time.Time `json:"created_at"`
}

// PosPinEvents is the managers' activity view: PIN sign-ins, wrong PINs,
// lockouts and till changes, newest first.
func (h *Handlers) PosPinEvents(w http.ResponseWriter, r *http.Request) {
	claims, ok := posManager(w, r)
	if !ok {
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT e.kind, coalesce(nullif(u.full_name, ''), u.email, ''), coalesce(d.name, ''), e.created_at
		FROM core.pos_pin_events e
		LEFT JOIN core.users u ON u.id = e.user_id
		LEFT JOIN core.pos_devices d ON d.id = e.device_id
		WHERE e.org_id = $1 ORDER BY e.created_at DESC LIMIT 100`, claims.OrgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read activity")
		return
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (posPinEvent, error) {
		var e posPinEvent
		return e, row.Scan(&e.Kind, &e.Name, &e.Device, &e.CreatedAt)
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read activity")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// posDevice resolves the X-Pos-Device header to an enrolled, unrevoked
// till: (device id, org id).
func (h *Handlers) posDeviceFrom(r *http.Request) (string, string, error) {
	token := r.Header.Get(PosDeviceHeader)
	if token == "" {
		return "", "", errors.New("no device")
	}
	var id, org string
	err := h.Pool.QueryRow(r.Context(), `
		SELECT id::text, org_id::text FROM core.pos_devices WHERE token_hash = $1 AND revoked_at IS NULL`,
		hashDeviceToken(token)).Scan(&id, &org)
	return id, org, err
}

// PosCashiers lists who can sign in by PIN on this enrolled till.
func (h *Handlers) PosCashiers(w http.ResponseWriter, r *http.Request) {
	_, org, err := h.posDeviceFrom(r)
	if err != nil {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "this till isn't trusted for PIN sign-in", "code": "device_not_enrolled"})
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT u.id::text, coalesce(nullif(u.full_name, ''), split_part(u.email, '@', 1)), false,
		       CASE WHEN p.locked_until > now() THEN p.locked_until END
		FROM core.pos_pins p JOIN core.users u ON u.id = p.user_id
		JOIN core.memberships m ON m.org_id = p.org_id AND m.user_id = p.user_id
		WHERE p.org_id = $1 ORDER BY 2`, org)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list cashiers")
		return
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (posPerson, error) {
		var p posPerson
		err := row.Scan(&p.UserID, &p.Name, &p.HasPin, &p.LockedUntil)
		p.HasPin = true
		return p, err
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list cashiers")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// PosPinLogin signs a cashier in with their PIN on an enrolled till.
func (h *Handlers) PosPinLogin(w http.ResponseWriter, r *http.Request) {
	deviceID, org, err := h.posDeviceFrom(r)
	if err != nil {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "this till isn't trusted for PIN sign-in; a manager can trust it in POS settings", "code": "device_not_enrolled"})
		return
	}
	var req struct {
		UserID string `json:"user_id"`
		Pin    string `json:"pin"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	email, role, ok := h.checkPin(w, r, deviceID, org, req.UserID, req.Pin, "signin")
	if !ok {
		return
	}
	// Never more than a member: owners', admins' and managers' powers need
	// their passkey.
	if role == "owner" || role == "admin" || role == "branch_manager" || role == "team_leader" {
		role = "member"
	}
	token, err := h.Issuer.IssueVia(req.UserID, org, role, email, PosVia, posAccess, posPinTokenTTL)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusOK, authResponse{Token: token, OrgID: org, Role: role, Email: email})
}

// checkPin checks userID's PIN on enrolled till deviceID, locking it after
// too many wrong tries, and records `event` when it's right. On a wrong or
// locked PIN it has already answered.
func (h *Handlers) checkPin(w http.ResponseWriter, r *http.Request, deviceID, org, userID, pin, event string) (email, role string, ok bool) {
	ctx := r.Context()
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not check the PIN")
		return "", "", false
	}
	defer tx.Rollback(ctx)
	var salt, hash []byte
	var failed int
	var lockedUntil *time.Time
	err = tx.QueryRow(ctx, `
		SELECT p.salt, p.hash, p.failed, p.locked_until, u.email, m.role
		FROM core.pos_pins p JOIN core.users u ON u.id = p.user_id
		JOIN core.memberships m ON m.org_id = p.org_id AND m.user_id = p.user_id
		WHERE p.org_id = $1 AND p.user_id::text = $2 FOR UPDATE OF p`, org, userID,
	).Scan(&salt, &hash, &failed, &lockedUntil, &email, &role)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "wrong PIN")
		return "", "", false
	}
	if lockedUntil != nil && lockedUntil.After(time.Now()) {
		writeJSON(w, http.StatusLocked, map[string]string{
			"error": "too many wrong PINs; ask a manager to unlock it, or try again after " + lockedUntil.Format("15:04"),
			"code":  "pin_locked",
		})
		return "", "", false
	}
	if subtle.ConstantTimeCompare(hashPin(pin, salt), hash) != 1 {
		failed++
		kind := "wrong_pin"
		if failed >= posPinMaxFailed {
			tx.Exec(ctx, `UPDATE core.pos_pins SET failed = 0, locked_until = now() + make_interval(secs => $3)
				WHERE org_id = $1 AND user_id::text = $2`, org, userID, posPinLockFor.Seconds())
			kind = "locked"
		} else {
			tx.Exec(ctx, `UPDATE core.pos_pins SET failed = $3 WHERE org_id = $1 AND user_id::text = $2`, org, userID, failed)
		}
		tx.Exec(ctx, `INSERT INTO core.pos_pin_events (org_id, user_id, device_id, kind) VALUES ($1, $2::uuid, NULLIF($3, '')::uuid, $4)`,
			org, userID, deviceID, kind)
		tx.Commit(ctx)
		if kind == "locked" {
			writeJSON(w, http.StatusLocked, map[string]string{
				"error": "too many wrong PINs; locked for 15 minutes or until a manager unlocks it",
				"code":  "pin_locked",
			})
			return "", "", false
		}
		writeJSON(w, http.StatusUnauthorized, map[string]any{
			"error": "wrong PIN", "code": "wrong_pin", "tries_left": posPinMaxFailed - failed,
		})
		return "", "", false
	}
	tx.Exec(ctx, `UPDATE core.pos_pins SET failed = 0, locked_until = NULL WHERE org_id = $1 AND user_id::text = $2`, org, userID)
	tx.Exec(ctx, `UPDATE core.pos_devices SET last_used_at = now() WHERE id::text = $1`, deviceID)
	tx.Exec(ctx, `INSERT INTO core.pos_pin_events (org_id, user_id, device_id, kind) VALUES ($1, $2::uuid, NULLIF($3, '')::uuid, $4)`,
		org, userID, deviceID, event)
	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "could not check the PIN")
		return "", "", false
	}
	return email, role, true
}

// PosResume (POST /auth/pos/resume, signed in): {"pin"} -> 204 when it is
// the signed-in cashier's own PIN. The till locks after 5 idle minutes and
// this lets the same cashier continue; on a till that isn't trusted the
// session was started with a passkey, so the PIN only resumes it. Wrong
// tries count towards the same lockout as signing in (plan 20.3).
func (h *Handlers) PosResume(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "sign in first")
		return
	}
	deviceID, _, _ := h.posDeviceFrom(r) // "" on a till that isn't trusted
	var req struct {
		Pin string `json:"pin"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	if _, _, ok := h.checkPin(w, r, deviceID, claims.OrgID, claims.Subject, req.Pin, "resumed"); !ok {
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// PosApprovalVia marks a till approval: a team leader's or manager's PIN
// approving one staff action (a return) at the till, for two minutes. It
// reaches no app on its own (no access); apps check it as a second token.
const PosApprovalVia = "pos-approval"

// PosApprove (POST /auth/pos/approve, enrolled till): {"user_id", "pin"}
// from a team leader or manager -> {"approval"}, signed and short.
func (h *Handlers) PosApprove(w http.ResponseWriter, r *http.Request) {
	deviceID, org, err := h.posDeviceFrom(r)
	if err != nil {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "this till isn't trusted for PINs; a manager can trust it in POS settings", "code": "device_not_enrolled"})
		return
	}
	var req struct {
		UserID string `json:"user_id"`
		Pin    string `json:"pin"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	if req.UserID == "" {
		writeError(w, http.StatusBadRequest, "choose who approves")
		return
	}
	var role string
	h.Pool.QueryRow(r.Context(), `SELECT role FROM core.memberships WHERE org_id = $1 AND user_id::text = $2`, org, req.UserID).Scan(&role)
	if role != "owner" && role != "admin" && role != "branch_manager" && role != "team_leader" {
		writeError(w, http.StatusForbidden, "only a team leader or a manager can approve")
		return
	}
	email, role, ok := h.checkPin(w, r, deviceID, org, req.UserID, req.Pin, "approved")
	if !ok {
		return
	}
	token, err := h.Issuer.IssueVia(req.UserID, org, role, email, PosApprovalVia, map[string]string{}, posApprovalTTL)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue the approval")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"approval": token, "expires_in": int(posApprovalTTL.Seconds())})
}

const posApprovalTTL = 2 * time.Minute
