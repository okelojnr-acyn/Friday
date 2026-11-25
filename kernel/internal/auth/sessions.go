package auth

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Sessions: every sign-in is a device the person can see ("Devices") and
// sign out. The token carries the session's id (sid); RequireAuth refuses
// a token whose session was signed out. Tokens from before sessions (no
// sid) still work until they expire.
type Sessions struct {
	Pool *pgxpool.Pool
	// TTL is how long a sign-in lasts (the token's lifetime).
	TTL time.Duration

	mu    sync.Mutex
	cache map[string]cachedSession
}

type cachedSession struct {
	active bool
	user   string // the cached answer is only for this person
	at     time.Time
}

// checkEvery: a signed-out device stops working within this long.
const checkEvery = 30 * time.Second

func (s *Sessions) start(r *http.Request, userID string) (string, error) {
	// Behind Caddy (and Cloudflare on Friday Host): the first forwarded address.
	ip := strings.TrimSpace(strings.Split(r.Header.Get("X-Forwarded-For"), ",")[0])
	if ip == "" {
		if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
			ip = host
		}
	}
	ua := r.UserAgent()
	if len(ua) > 400 {
		ua = ua[:400]
	}
	var id string
	err := s.Pool.QueryRow(r.Context(),
		`INSERT INTO core.sessions (user_id, user_agent, ip) VALUES ($1, $2, $3) RETURNING id::text`,
		userID, ua, ip).Scan(&id)
	return id, err
}

// Active: sid belongs to userID and isn't signed out. Cached briefly, and
// marks the device as seen (at most every few minutes).
func (s *Sessions) Active(ctx context.Context, sid, userID string) bool {
	s.mu.Lock()
	if c, ok := s.cache[sid]; ok && c.user == userID && time.Since(c.at) < checkEvery {
		s.mu.Unlock()
		return c.active
	}
	s.mu.Unlock()
	var active bool
	err := s.Pool.QueryRow(ctx, `
		UPDATE core.sessions SET last_seen_at = CASE WHEN last_seen_at < now() - interval '5 minutes' THEN now() ELSE last_seen_at END
		WHERE id::text = $1 AND user_id::text = $2 RETURNING revoked_at IS NULL`, sid, userID).Scan(&active)
	if errors.Is(err, pgx.ErrNoRows) {
		return false // no such session: signed out (or someone else's)
	}
	if err != nil {
		// A database hiccup doesn't sign anyone out; not cached, so the
		// next request asks again.
		return true
	}
	s.mu.Lock()
	if s.cache == nil || len(s.cache) > 10000 {
		s.cache = map[string]cachedSession{}
	}
	s.cache[sid] = cachedSession{active: active, user: userID, at: time.Now()}
	s.mu.Unlock()
	return active
}

func (s *Sessions) forget(sid string) {
	s.mu.Lock()
	delete(s.cache, sid)
	s.mu.Unlock()
}

// Prune removes sessions over 30 days old (they expired long before).
func (s *Sessions) Prune(ctx context.Context) error {
	_, err := s.Pool.Exec(ctx, `DELETE FROM core.sessions WHERE created_at < now() - interval '30 days'`)
	return err
}

// Device is one signed-in device, as "Devices" shows it.
type Device struct {
	ID         string    `json:"id"`
	Label      string    `json:"label"`
	IP         string    `json:"ip"`
	SignedInAt time.Time `json:"signed_in_at"`
	LastSeenAt time.Time `json:"last_seen_at"`
	Current    bool      `json:"current"`
}

// ListDevices (GET /auth/sessions): the caller's signed-in devices.
func (s *Sessions) ListDevices(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	rows, err := s.Pool.Query(r.Context(), `
		SELECT id::text, user_agent, ip, created_at, last_seen_at FROM core.sessions
		WHERE user_id::text = $1 AND revoked_at IS NULL AND created_at > now() - make_interval(secs => $2)
		ORDER BY last_seen_at DESC`, claims.Subject, s.ttl().Seconds())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []Device{}
	for rows.Next() {
		var d Device
		var ua string
		if rows.Scan(&d.ID, &ua, &d.IP, &d.SignedInAt, &d.LastSeenAt) == nil {
			d.Label, d.Current = DeviceLabel(ua), d.ID == claims.Sid
			out = append(out, d)
		}
	}
	writeJSON(w, http.StatusOK, out)
}

// SignOutDevice (DELETE /auth/sessions/{id}): signs one of the caller's
// devices out (this one too, if they choose it).
func (s *Sessions) SignOutDevice(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	id := r.PathValue("id")
	tag, err := s.Pool.Exec(r.Context(),
		`UPDATE core.sessions SET revoked_at = now() WHERE id::text = $1 AND user_id::text = $2 AND revoked_at IS NULL`, id, claims.Subject)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no such device")
		return
	}
	s.forget(id)
	w.WriteHeader(http.StatusNoContent)
}

// SignOutThis (POST /auth/sessions/sign-out): signing out ends this
// device's session too, so it leaves the Devices list.
func (s *Sessions) SignOutThis(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if claims.Sid != "" {
		if _, err := s.Pool.Exec(r.Context(), `UPDATE core.sessions SET revoked_at = now() WHERE id::text = $1 AND revoked_at IS NULL`, claims.Sid); err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		s.forget(claims.Sid)
	}
	w.WriteHeader(http.StatusNoContent)
}

// SignOutOthers (POST /auth/sessions/sign-out-others): every device but this one.
func (s *Sessions) SignOutOthers(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	rows, err := s.Pool.Query(r.Context(), `
		UPDATE core.sessions SET revoked_at = now()
		WHERE user_id::text = $1 AND id::text <> $2 AND revoked_at IS NULL RETURNING id::text`, claims.Subject, claims.Sid)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	n := 0
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			s.forget(id)
			n++
		}
	}
	rows.Close()
	writeJSON(w, http.StatusOK, map[string]int{"signed_out": n})
}

func (s *Sessions) ttl() time.Duration {
	if s.TTL > 0 {
		return s.TTL
	}
	return 24 * time.Hour
}

// DeviceLabel turns a browser's user agent into "Chrome on Windows".
func DeviceLabel(ua string) string {
	browser := "Browser"
	for _, b := range []struct{ token, name string }{
		{"Edg/", "Edge"}, {"OPR/", "Opera"}, {"SamsungBrowser/", "Samsung Internet"}, {"Firefox/", "Firefox"},
		{"CriOS/", "Chrome"}, {"Chrome/", "Chrome"}, {"Safari/", "Safari"},
	} {
		if strings.Contains(ua, b.token) {
			browser = b.name
			break
		}
	}
	os := ""
	for _, o := range []struct{ token, name string }{
		{"Android", "Android"}, {"iPhone", "iPhone"}, {"iPad", "iPad"}, {"Windows", "Windows"},
		{"Mac OS X", "Mac"}, {"CrOS", "ChromeOS"}, {"Linux", "Linux"},
	} {
		if strings.Contains(ua, o.token) {
			os = o.name
			break
		}
	}
	if ua == "" {
		return "Unknown device"
	}
	if os == "" {
		return browser
	}
	return browser + " on " + os
}

// Passkey is one of the caller's passkeys, as Account shows it.
type Passkey struct {
	ID          string    `json:"id"`
	DeviceLabel string    `json:"device_label"`
	CreatedAt   time.Time `json:"created_at"`
}

// ListPasskeys (GET /auth/passkeys): the caller's passkeys.
func (s *Sessions) ListPasskeys(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	rows, err := s.Pool.Query(r.Context(),
		`SELECT id::text, device_label, created_at FROM core.webauthn_credentials WHERE user_id::text = $1 ORDER BY created_at`, claims.Subject)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []Passkey{}
	for rows.Next() {
		var p Passkey
		if rows.Scan(&p.ID, &p.DeviceLabel, &p.CreatedAt) == nil {
			out = append(out, p)
		}
	}
	writeJSON(w, http.StatusOK, out)
}

// DeletePasskey (DELETE /auth/passkeys/{id}): removes one of the caller's
// passkeys. The last one can go too: email codes still sign in.
func (s *Sessions) DeletePasskey(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	tag, err := s.Pool.Exec(r.Context(),
		`DELETE FROM core.webauthn_credentials WHERE id::text = $1 AND user_id::text = $2`, r.PathValue("id"), claims.Subject)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no such passkey")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}


// accessCache: when each person's access last changed, checked at most
// every checkEvery (like Active).
var accessCache = struct {
	sync.Mutex
	m map[string]cachedChange
}{m: map[string]cachedChange{}}

type cachedChange struct {
	at      time.Time // when access last changed (zero: never)
	checked time.Time
}

// AccessChangedSince: the person's role, jobs, locations or manager changed
// after `issued` (a token from before carries the old access). A database
// hiccup says no: nobody is locked out by it.
func (s *Sessions) AccessChangedSince(ctx context.Context, orgID, userID string, issued time.Time) bool {
	key := orgID + ":" + userID
	accessCache.Lock()
	c, ok := accessCache.m[key]
	accessCache.Unlock()
	if !ok || time.Since(c.checked) >= checkEvery {
		var at *time.Time
		if err := s.Pool.QueryRow(ctx, `SELECT access_changed_at FROM core.memberships WHERE org_id::text = $1 AND user_id::text = $2`,
			orgID, userID).Scan(&at); err != nil {
			return false
		}
		c = cachedChange{checked: time.Now()}
		if at != nil {
			c.at = *at
		}
		accessCache.Lock()
		if len(accessCache.m) > 10000 {
			accessCache.m = map[string]cachedChange{}
		}
		accessCache.m[key] = c
		accessCache.Unlock()
	}
	// Tokens carry whole seconds: a change in the same second as issuing
	// isn't counted, or a fresh token would look stale.
	return !c.at.IsZero() && c.at.After(issued.Add(time.Second))
}

func forgetAccess(orgID, userID string) {
	accessCache.Lock()
	delete(accessCache.m, orgID+":"+userID)
	accessCache.Unlock()
}
