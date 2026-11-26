package org

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// Standard until changed; a preset name takes its numbers; custom keeps
// what's sent; only owners and admins change it; nonsense is refused.
func TestSpendingPolicy(t *testing.T) {
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
	var orgID string
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	p := &People{Pool: pool, InternalToken: "tok"}
	as := func(role string, req *http.Request) *http.Request {
		return req.WithContext(auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, Role: role, RegisteredClaims: jwt.RegisteredClaims{Subject: "u"}}))
	}
	get := func() SpendingPolicy {
		rec := httptest.NewRecorder()
		p.GetSpendingPolicy(rec, as("member", httptest.NewRequest("GET", "/orgs/spending-policy", nil)))
		var v spendingView
		json.Unmarshal(rec.Body.Bytes(), &v)
		if len(v.Presets) != 3 {
			t.Fatalf("presets: %s", rec.Body)
		}
		return v.SpendingPolicy
	}
	put := func(role, body string) int {
		rec := httptest.NewRecorder()
		p.PutSpendingPolicy(rec, as(role, httptest.NewRequest("PUT", "/orgs/spending-policy", bytes.NewBufferString(body))))
		return rec.Code
	}
	if got := get(); got != SpendingPresets["standard"] {
		t.Fatalf("standard by default: %+v", got)
	}
	if code := put("branch_manager", `{"preset":"simple"}`); code != http.StatusForbidden {
		t.Fatalf("a manager changed it: %d", code)
	}
	if code := put("owner", `{"preset":"strict"}`); code != http.StatusOK || get() != SpendingPresets["strict"] {
		t.Fatalf("strict: %d %+v", code, get())
	}
	custom := SpendingPresets["standard"]
	custom.Preset, custom.TillPayouts = "custom", true
	raw, _ := json.Marshal(custom)
	if code := put("admin", string(raw)); code != http.StatusOK || get() != custom {
		t.Fatalf("custom: %d %+v", code, get())
	}
	if code := put("owner", `{"preset":"custom","petty_float":100,"petty_slip_max":500}`); code != http.StatusBadRequest {
		t.Fatalf("a slip over the float: %d", code)
	}
	// Apps read it too.
	req := httptest.NewRequest("GET", "/internal/people/"+orgID+"/spending-policy", nil)
	req.SetPathValue("org_id", orgID)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	p.SpendingPolicyFor(rec, req)
	var s SpendingPolicy
	json.Unmarshal(rec.Body.Bytes(), &s)
	if rec.Code != http.StatusOK || s != custom {
		t.Fatalf("internal read: %d %+v", rec.Code, s)
	}
}
