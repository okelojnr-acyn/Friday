// Package push sends phone notifications (Web Push) to Minions: the same
// notice the inbox files and Guss sends (internal/inbox), to every phone or
// browser the person turned notifications on in.
package push

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/SherClockHolmes/webpush-go"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/inbox"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
)

// Push holds the install's VAPID keys and serves and sends notifications.
type Push struct {
	Pool *pgxpool.Pool
	Box  *sealed.Box
	// WebURL is Friday's web address: the VAPID contact, and where links lead.
	WebURL string
	// Client is replaced in tests.
	Client webpush.HTTPClient

	once            sync.Mutex
	public, private string
}

// pushHosts are the push services browsers use. A subscription's endpoint
// comes from the phone, so the kernel only ever posts to these (never to an
// address of the caller's choosing).
var pushHosts = []string{
	"fcm.googleapis.com", "android.googleapis.com", // Chrome, Edge on Android, most Android browsers
	".push.services.mozilla.com",            // Firefox
	"web.push.apple.com", ".push.apple.com", // Safari, iPhone home-screen apps
	".notify.windows.com", // Edge on Windows
}

// AllowedEndpoint: https on a known push service.
func AllowedEndpoint(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.User != nil || u.Port() != "" || len(raw) > 1000 {
		return false
	}
	host := strings.ToLower(u.Hostname())
	for _, h := range pushHosts {
		if host == h || (strings.HasPrefix(h, ".") && strings.HasSuffix(host, h)) {
			return true
		}
	}
	return false
}

// keys loads the VAPID key pair, making it the first time it's needed.
func (p *Push) keys(ctx context.Context) (string, string, error) {
	p.once.Lock()
	defer p.once.Unlock()
	if p.public != "" {
		return p.public, p.private, nil
	}
	if p.Box == nil {
		return "", "", errors.New("FRIDAY_SECRETS_KEY isn't set: phone notifications are off")
	}
	var public string
	var sealedPriv []byte
	err := p.Pool.QueryRow(ctx, `SELECT public_key, private_key FROM core.push_keys WHERE id = 1`).Scan(&public, &sealedPriv)
	if errors.Is(err, pgx.ErrNoRows) {
		priv, pub, gerr := webpush.GenerateVAPIDKeys()
		if gerr != nil {
			return "", "", gerr
		}
		sealedNew, serr := p.Box.Seal([]byte(priv))
		if serr != nil {
			return "", "", serr
		}
		// Two kernels starting together: the first one's pair wins.
		if _, err = p.Pool.Exec(ctx, `INSERT INTO core.push_keys (id, public_key, private_key) VALUES (1, $1, $2) ON CONFLICT (id) DO NOTHING`, pub, sealedNew); err != nil {
			return "", "", err
		}
		err = p.Pool.QueryRow(ctx, `SELECT public_key, private_key FROM core.push_keys WHERE id = 1`).Scan(&public, &sealedPriv)
	}
	if err != nil {
		return "", "", err
	}
	priv, err := p.Box.Open(sealedPriv)
	if err != nil {
		return "", "", err
	}
	p.public, p.private = public, string(priv)
	return p.public, p.private, nil
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

// Key (GET /me/push/key): the public key a browser subscribes with.
func (p *Push) Key(w http.ResponseWriter, r *http.Request) {
	pub, _, err := p.keys(r.Context())
	if err != nil {
		log.Printf("push keys: %v", err)
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "phone notifications aren't available on this Friday"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"public_key": pub})
}

type subscription struct {
	Endpoint string `json:"endpoint"`
	Keys     struct {
		P256dh string `json:"p256dh"`
		Auth   string `json:"auth"`
	} `json:"keys"`
}

// Subscribe (POST /me/push/subscriptions): this phone, for me in this
// business. A phone moving to another person or business is moved too.
func (p *Push) Subscribe(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	var s subscription
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&s); err != nil ||
		!AllowedEndpoint(s.Endpoint) || s.Keys.P256dh == "" || s.Keys.Auth == "" || len(s.Keys.P256dh) > 200 || len(s.Keys.Auth) > 100 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "that isn't a browser push subscription"})
		return
	}
	ua := r.UserAgent()
	if len(ua) > 300 {
		ua = ua[:300]
	}
	if _, err := p.Pool.Exec(r.Context(), `
		INSERT INTO core.push_subscriptions (org_id, user_id, endpoint, p256dh, auth, user_agent)
		VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
		ON CONFLICT (endpoint) DO UPDATE SET org_id = EXCLUDED.org_id, user_id = EXCLUDED.user_id,
		       p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, user_agent = EXCLUDED.user_agent`,
		c.OrgID, c.Subject, s.Endpoint, s.Keys.P256dh, s.Keys.Auth, ua); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "couldn't save"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Unsubscribe (POST /me/push/unsubscribe, {"endpoint"}): this phone
// stops (turned off, or signing out). Only my own.
func (p *Push) Unsubscribe(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	var s subscription
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&s); err != nil || s.Endpoint == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": `send {"endpoint"}`})
		return
	}
	if _, err := p.Pool.Exec(r.Context(), `DELETE FROM core.push_subscriptions WHERE endpoint = $1 AND user_id::text = $2`, s.Endpoint, c.Subject); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "couldn't save"})
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Quiet: 21:00-07:00 in the person's zone (shared with Guss's notices).
func Quiet(t time.Time, tz string) bool {
	loc, err := time.LoadLocation(tz)
	if err != nil || tz == "" {
		loc = time.UTC
	}
	h := t.In(loc).Hour()
	return h >= 21 || h < 7
}

// Payload is what the service worker shows (public/minions-push.js).
type Payload struct {
	Title  string `json:"title"`
	Body   string `json:"body"`
	URL    string `json:"url"`
	Tag    string `json:"tag"`
	Silent bool   `json:"silent"`
}

// Send pushes an event's notice to the phones of the people it names. Best
// effort: a push service being down never holds up the inbox or Guss, so
// failures are logged, not returned. A phone the service says is gone
// (404, 410) is forgotten.
func (p *Push) Send(ctx context.Context, eventID, orgID, typ string, payload []byte) {
	var n inbox.Notice
	if json.Unmarshal(payload, &n) != nil || len(n.ToUserIDs) == 0 {
		return
	}
	var orgTZ string
	_ = p.Pool.QueryRow(ctx, `SELECT time_zone FROM core.orgs WHERE id::text = $1`, orgID).Scan(&orgTZ)
	m, ok := inbox.Compose(typ, n)
	if !ok {
		return
	}
	rows, err := p.Pool.Query(ctx, `
		SELECT s.id, s.endpoint, s.p256dh, s.auth, m.role, COALESCE(NULLIF(u.time_zone, ''), $3)
		FROM core.push_subscriptions s
		JOIN core.memberships m ON m.org_id = s.org_id AND m.user_id = s.user_id
		JOIN core.users u ON u.id = s.user_id
		WHERE s.org_id::text = $1 AND s.user_id::text = ANY($2)`, orgID, n.ToUserIDs, orgTZ)
	if err != nil {
		log.Printf("push: %v", err)
		return
	}
	type target struct {
		id                               int64
		endpoint, p256dh, auth, role, tz string
	}
	var targets []target
	for rows.Next() {
		var t target
		if rows.Scan(&t.id, &t.endpoint, &t.p256dh, &t.auth, &t.role, &t.tz) == nil {
			targets = append(targets, t)
		}
	}
	rows.Close()
	if len(targets) == 0 {
		return
	}
	pub, priv, err := p.keys(ctx)
	if err != nil {
		log.Printf("push keys: %v", err)
		return
	}
	now := time.Now()
	for _, t := range targets {
		if !AllowedEndpoint(t.endpoint) {
			continue
		}
		body, _ := json.Marshal(Payload{Title: m.Title, Body: m.Body, URL: m.Path(t.role), Tag: eventID, Silent: Quiet(now, t.tz)})
		resp, err := webpush.SendNotificationWithContext(ctx, body,
			&webpush.Subscription{Endpoint: t.endpoint, Keys: webpush.Keys{P256dh: t.p256dh, Auth: t.auth}},
			&webpush.Options{
				HTTPClient: p.client(), Subscriber: p.contact(), VAPIDPublicKey: pub, VAPIDPrivateKey: priv,
				TTL: 24 * 3600, Urgency: webpush.UrgencyHigh,
			})
		if err != nil {
			log.Printf("push to a phone failed: %v", err)
			continue
		}
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
		resp.Body.Close()
		if resp.StatusCode == http.StatusNotFound || resp.StatusCode == http.StatusGone {
			_, _ = p.Pool.Exec(ctx, `DELETE FROM core.push_subscriptions WHERE id = $1`, t.id)
		} else if resp.StatusCode >= 300 {
			log.Printf("push service answered %d", resp.StatusCode)
		}
	}
}

func (p *Push) client() webpush.HTTPClient {
	if p.Client != nil {
		return p.Client
	}
	return &http.Client{
		Timeout: 10 * time.Second,
		// A push service answers directly; a redirect could point anywhere.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

// contact is the VAPID subject push services can reach the sender at.
func (p *Push) contact() string {
	if strings.HasPrefix(p.WebURL, "https://") {
		return strings.TrimRight(p.WebURL, "/")
	}
	return "https://fridayhost.dev"
}
