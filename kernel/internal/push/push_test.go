package push

import (
	"bytes"
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/inbox"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
)

func TestOnlyRealPushServices(t *testing.T) {
	for raw, ok := range map[string]bool{
		"https://fcm.googleapis.com/fcm/send/abc":              true,
		"https://updates.push.services.mozilla.com/wpush/v2/x": true,
		"https://web.push.apple.com/QGz":                       true,
		"https://wns2-par02p.notify.windows.com/w/?token=x":    true,
		"http://fcm.googleapis.com/fcm/send/abc":               false, // not https
		"https://fcm.googleapis.com:8443/x":                    false, // odd port
		"https://169.254.169.254/latest/meta-data":             false, // the cloud's metadata
		"https://localhost/x":                                  false,
		"https://evilpush.services.mozilla.com.attacker.io/x":  false,
		"https://user:pw@fcm.googleapis.com/x":                 false,
	} {
		if AllowedEndpoint(raw) != ok {
			t.Errorf("%s: allowed=%v", raw, !ok)
		}
	}
	at := time.Date(2026, 11, 25, 19, 0, 0, 0, time.UTC) // 22:00 in Nairobi
	if !Quiet(at, "Africa/Nairobi") || Quiet(at, "America/New_York") {
		t.Error("quiet hours follow the person's zone")
	}
}

// fakeService stands in for a push service: it records what it got and
// answers with `status`.
type fakeService struct {
	status int
	got    []*http.Request
}

func (f *fakeService) Do(r *http.Request) (*http.Response, error) {
	f.got = append(f.got, r)
	return &http.Response{StatusCode: f.status, Body: io.NopCloser(strings.NewReader(""))}, nil
}

func browserKeys(t *testing.T) (p256dh, authKey string) {
	k, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	a := make([]byte, 16)
	rand.Read(a)
	return base64.RawURLEncoding.EncodeToString(k.PublicKey().Bytes()), base64.RawURLEncoding.EncodeToString(a)
}

func TestSubscribeSendForget(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	key := make([]byte, 32)
	rand.Read(key)
	box, err := sealed.New(base64.StdEncoding.EncodeToString(key))
	if err != nil {
		t.Fatal(err)
	}
	var orgID, sam, ann string
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	for _, id := range []*string{&sam, &ann} {
		if err := pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES (gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(id); err != nil {
			t.Fatal(err)
		}
		if _, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'member')`, orgID, *id); err != nil {
			t.Fatal(err)
		}
	}
	svc := &fakeService{status: http.StatusCreated}
	p := &Push{Pool: pool, Box: box, WebURL: "https://friday.duka.fridayhost.dev", Client: svc}
	as := func(user string, r *http.Request) *http.Request {
		return r.WithContext(auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, RegisteredClaims: jwt.RegisteredClaims{Subject: user}}))
	}
	call := func(h http.HandlerFunc, user, method, body string) int {
		rec := httptest.NewRecorder()
		h(rec, as(user, httptest.NewRequest(method, "/me/push/subscriptions", bytes.NewBufferString(body))))
		return rec.Code
	}

	rec := httptest.NewRecorder()
	p.Key(rec, as(sam, httptest.NewRequest("GET", "/me/push/key", nil)))
	var k struct {
		PublicKey string `json:"public_key"`
	}
	json.Unmarshal(rec.Body.Bytes(), &k)
	if rec.Code != http.StatusOK || k.PublicKey == "" {
		t.Fatalf("key: %d %s", rec.Code, rec.Body)
	}
	p2 := &Push{Pool: pool, Box: box}
	if pub, _, _ := p2.keys(ctx); pub != k.PublicKey {
		t.Fatal("the key pair is made once and kept")
	}

	dh, au := browserKeys(t)
	endpoint := "https://fcm.googleapis.com/fcm/send/sam-" + orgID
	sub := `{"endpoint":"` + endpoint + `","keys":{"p256dh":"` + dh + `","auth":"` + au + `"}}`
	if code := call(p.Subscribe, sam, "POST", strings.Replace(sub, "fcm.googleapis.com", "169.254.169.254", 1)); code != http.StatusBadRequest {
		t.Fatalf("a made-up endpoint was accepted: %d", code)
	}
	if code := call(p.Subscribe, sam, "POST", sub); code != http.StatusNoContent {
		t.Fatalf("subscribe: %d", code)
	}

	event, _ := json.Marshal(inbox.Notice{ToUserIDs: []string{sam}, FromName: "Tom", AmountCents: 150000, Currency: "KES", Description: "taxi"})
	p.Send(ctx, "ev-1", orgID, "minions.approval.needed", event)
	if len(svc.got) != 1 || svc.got[0].URL.String() != endpoint ||
		svc.got[0].Header.Get("Content-Encoding") != "aes128gcm" || !strings.HasPrefix(svc.got[0].Header.Get("Authorization"), "vapid ") {
		t.Fatalf("push sent: %d %+v", len(svc.got), svc.got)
	}

	// Ann can't take Sam's phone off.
	if call(p.Unsubscribe, ann, "DELETE", `{"endpoint":"`+endpoint+`"}`); count(t, pool, endpoint) != 1 {
		t.Fatal("someone else removed the phone")
	}
	// The push service says the phone is gone: it's forgotten.
	svc.status = http.StatusGone
	p.Send(ctx, "ev-2", orgID, "minions.approval.needed", event)
	if count(t, pool, endpoint) != 0 {
		t.Fatal("a gone phone stays")
	}
}

func count(t *testing.T, pool *pgxpool.Pool, endpoint string) int {
	var n int
	if err := pool.QueryRow(context.Background(), `SELECT count(*) FROM core.push_subscriptions WHERE endpoint = $1`, endpoint).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}
