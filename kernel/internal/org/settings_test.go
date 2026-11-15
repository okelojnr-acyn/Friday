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

func TestSettingsDefaultsAndWhoMayChangeThem(t *testing.T) {
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
	s := &Settings{Pool: pool}
	call := func(method, role, via, body string) (int, map[string]any) {
		r := httptest.NewRequest(method, "/orgs/settings", bytes.NewBufferString(body))
		r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: role, Via: via, RegisteredClaims: jwt.RegisteredClaims{Subject: "u"}}))
		w := httptest.NewRecorder()
		if method == http.MethodGet {
			s.Get(w, r)
		} else {
			s.Put(w, r)
		}
		var out map[string]any
		json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}
	code, v := call(http.MethodGet, "member", "", "")
	if code != 200 || v["currency"] != "KES" || v["tax_rate_bp"] != float64(1600) || v["prices_include_tax"] != true {
		t.Fatalf("defaults: %d %v", code, v)
	}
	if code, _ := call(http.MethodPut, "member", "", `{"currency":"USD"}`); code != http.StatusForbidden {
		t.Fatalf("member change: %d", code)
	}
	if code, _ := call(http.MethodPut, "owner", "guss", `{"currency":"USD"}`); code != http.StatusForbidden {
		t.Fatalf("assistant change: %d", code)
	}
	if code, _ := call(http.MethodPut, "admin", "", `{"currency":"shillings"}`); code != http.StatusBadRequest {
		t.Fatalf("bad currency: %d", code)
	}
	code, v = call(http.MethodPut, "admin", "", `{"currency":"ugx","tax_rate_bp":1800,"prices_include_tax":false}`)
	if code != 200 || v["currency"] != "UGX" || v["tax_rate_bp"] != float64(1800) || v["prices_include_tax"] != false {
		t.Fatalf("update: %d %v", code, v)
	}
}
