package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// Owner, 2026-11-26: a staff member's new jobs didn't reach the staff app
// until they signed in again. Now an older token is refused once their
// access changes, and /auth/refresh swaps it for one with the new access.
func TestChangedAccessIsRefreshedNotKept(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	var orgID, userID string
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES (gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&userID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role, perms) VALUES ($1, $2, 'member', '{cashier}')`, orgID, userID); err != nil {
		t.Fatal(err)
	}
	iss := NewIssuer("test-secret", time.Hour)
	iss.Sessions = &Sessions{Pool: pool}
	iss.Scope = func(ctx context.Context, userID, orgID, role string) ([]string, []string, []string, error) {
		var perms []string
		err := pool.QueryRow(ctx, `SELECT perms FROM core.memberships WHERE org_id::text = $1 AND user_id::text = $2`, orgID, userID).Scan(&perms)
		return perms, []string{"*"}, nil, err
	}
	req := httptest.NewRequest("POST", "/auth/otp/verify", nil)
	old, err := iss.IssueFor(req, userID, orgID, "member", "sam@x.test")
	if err != nil {
		t.Fatal(err)
	}
	guarded := RequireAuth(iss)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) }))
	call := func(token string) (int, map[string]string) {
		r := httptest.NewRequest("GET", "/orgs/me/permissions", nil)
		r.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		guarded.ServeHTTP(rec, r)
		var body map[string]string
		json.Unmarshal(rec.Body.Bytes(), &body)
		return rec.Code, body
	}
	if code, _ := call(old); code != http.StatusNoContent {
		t.Fatalf("fresh token refused: %d", code)
	}

	// People changes their jobs (cashier -> warehouse, logistics), later than the token.
	time.Sleep(2100 * time.Millisecond)
	if _, err := pool.Exec(ctx, `UPDATE core.memberships SET perms = '{warehouse,logistics}', access_changed_at = now() WHERE org_id::text = $1 AND user_id::text = $2`, orgID, userID); err != nil {
		t.Fatal(err)
	}
	forgetAccess(orgID, userID) // another kernel would see it within checkEvery
	if code, body := call(old); code != http.StatusUnauthorized || body["code"] != "access_changed" {
		t.Fatalf("old token still works: %d %v", code, body)
	}

	h := &Handlers{Pool: pool, Issuer: iss}
	refresh := func(token string) (int, authResponse) {
		r := httptest.NewRequest("POST", "/auth/refresh", nil)
		r.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		h.Refresh(rec, r)
		var out authResponse
		json.Unmarshal(rec.Body.Bytes(), &out)
		return rec.Code, out
	}
	code, fresh := refresh(old)
	if code != http.StatusOK || fresh.Token == "" {
		t.Fatalf("refresh: %d", code)
	}
	if code, _ := call(fresh.Token); code != http.StatusNoContent {
		t.Fatalf("the refreshed token is refused: %d", code)
	}
	claims, _ := iss.Verify(fresh.Token)
	if !slices.Contains(claims.Perms, "logistics") || slices.Contains(claims.Perms, "cashier") {
		t.Fatalf("refreshed token has the old jobs: %v", claims.Perms)
	}
	before, _ := iss.Verify(old)
	if claims.Sid == "" || claims.Sid != before.Sid {
		t.Fatal("the refresh keeps the same device (session)")
	}

	// A signed-out device can't refresh.
	if _, err := pool.Exec(ctx, `UPDATE core.sessions SET revoked_at = now() WHERE id::text = $1`, claims.Sid); err != nil {
		t.Fatal(err)
	}
	iss.Sessions.forget(claims.Sid)
	if code, _ := refresh(fresh.Token); code != http.StatusUnauthorized {
		t.Fatalf("a signed-out device refreshed: %d", code)
	}
}
