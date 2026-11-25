package org

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// Who showed up since the business's midnight: a till sign-in today
// (with the till), or Friday opened today; yesterday's doesn't count.
func TestSeenSince(t *testing.T) {
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
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	var orgID, device string
	must(pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID))
	must(pool.QueryRow(ctx, `INSERT INTO core.pos_devices (org_id, name, token_hash) VALUES ($1, 'Till 2', gen_random_uuid()::text) RETURNING id::text`, orgID).Scan(&device))
	person := func() string {
		var id string
		must(pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES (gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&id))
		_, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'member')`, orgID, id)
		must(err)
		return id
	}
	ann, ben, cy := person(), person(), person()
	since := time.Now().Add(-2 * time.Hour).UTC()
	_, err = pool.Exec(ctx, `INSERT INTO core.pos_pin_events (org_id, user_id, device_id, kind, created_at) VALUES ($1, $2, $3, 'signin', now() - interval '1 hour')`, orgID, ann, device)
	must(err)
	_, err = pool.Exec(ctx, `INSERT INTO core.pos_pin_events (org_id, user_id, device_id, kind, created_at) VALUES ($1, $2, $3, 'signin', now() - interval '1 day')`, orgID, ben, device)
	must(err)
	_, err = pool.Exec(ctx, `INSERT INTO core.sessions (user_id, created_at, last_seen_at) VALUES ($1, now() - interval '3 days', now() - interval '5 minutes')`, cy)
	must(err)

	p := &People{Pool: pool, InternalToken: "tok"}
	q := url.Values{"since": {since.Format(time.RFC3339)}, "user_id": {ann, ben, cy}}
	req := httptest.NewRequest("GET", "/internal/people/"+orgID+"/seen?"+q.Encode(), nil)
	req.SetPathValue("org_id", orgID)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	p.SeenSince(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("seen: %d %s", rec.Code, rec.Body)
	}
	var out []Seen
	must(json.Unmarshal(rec.Body.Bytes(), &out))
	by := map[string]Seen{}
	for _, s := range out {
		by[s.UserID] = s
	}
	if s, ok := by[ann]; !ok || s.Till != "Till 2" || s.TillAt == nil {
		t.Fatalf("Ann at Till 2 today: %+v", s)
	}
	if _, ok := by[ben]; ok {
		t.Fatal("Ben's sign-in was yesterday")
	}
	if s, ok := by[cy]; !ok || s.AppFirstAt != nil || s.LastAt == nil {
		t.Fatalf("Cy on the app today (session from before: no arrival time): %+v", s)
	}
}
