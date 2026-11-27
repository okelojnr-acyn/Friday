package shop

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

func TestShopKeysAndPublicCatalog(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set in CI")
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
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug, currency) VALUES ('Duka', $1, 'KES') RETURNING id::text`,
		fmt.Sprintf("duka-%d", time.Now().UnixNano())).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	issuer := auth.NewIssuer(strings.Repeat("s", 32), time.Hour)
	var seen *auth.Claims
	inventory := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen, _ = issuer.Verify(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
		if r.URL.Path == "/shop/catalog" {
			w.Write([]byte(`[{"id":"p1","name":"Tea","price_cents":35000,"in_stock":true}]`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer inventory.Close()
	h := &Handlers{Pool: pool, Issuer: issuer, InventoryURL: inventory.URL}

	as := func(role string, hf http.HandlerFunc, method, path string, body any) *httptest.ResponseRecorder {
		var b bytes.Buffer
		json.NewEncoder(&b).Encode(body)
		r := httptest.NewRequest(method, path, &b)
		r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: role}))
		w := httptest.NewRecorder()
		hf(w, r)
		return w
	}
	if w := as("member", h.Create, "POST", "/orgs/shop-keys", map[string]any{}); w.Code != 403 {
		t.Fatalf("a member made a key: %d", w.Code)
	}
	if w := as("owner", h.Create, "POST", "/orgs/shop-keys", map[string]any{"origins": []string{"ftp://x"}}); w.Code != 400 {
		t.Fatalf("bad site accepted: %d", w.Code)
	}
	w := as("owner", h.Create, "POST", "/orgs/shop-keys", map[string]any{"name": "Web", "origins": []string{"https://duka.example/"}})
	var key KeyView
	json.NewDecoder(w.Body).Decode(&key)
	if w.Code != 201 || !strings.HasPrefix(key.Key, "fpk_") || len(key.Origins) != 1 || key.Origins[0] != "https://duka.example" {
		t.Fatalf("create: %d %+v", w.Code, key)
	}

	get := func(path, origin string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", path, nil)
		if origin != "" {
			r.Header.Set("Origin", origin)
		}
		w := httptest.NewRecorder()
		w.Header().Set("Access-Control-Allow-Origin", "https://friday.example") // the kernel's own CORS ran first
		h.Catalog(w, r)
		return w
	}
	if w := get("/public/catalog", ""); w.Code != 401 {
		t.Fatalf("no key: %d", w.Code)
	}
	w = get("/public/catalog?key="+key.Key, "https://duka.example")
	if w.Code != 200 || w.Header().Get("Access-Control-Allow-Origin") != "https://duka.example" ||
		!strings.Contains(w.Body.String(), `"currency":"KES"`) || !strings.Contains(w.Body.String(), `"name":"Tea"`) {
		t.Fatalf("catalog: %d %q %s", w.Code, w.Header().Get("Access-Control-Allow-Origin"), w.Body)
	}
	if seen == nil || seen.Via != Via || seen.Role != "shop" || seen.OrgID != orgID || seen.ExpiresAt.Sub(time.Now()) > 2*time.Minute {
		t.Fatalf("Inventory got %+v", seen)
	}
	if w := get("/public/catalog?key="+key.Key, "https://elsewhere.example"); w.Code != 403 || w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("another site: %d %q", w.Code, w.Header().Get("Access-Control-Allow-Origin"))
	}

	pool.Exec(ctx, `UPDATE core.orgs SET suspended_at = now() WHERE id::text = $1`, orgID)
	if w := get("/public/catalog?key="+key.Key, ""); w.Code != 402 {
		t.Fatalf("suspended shop: %d", w.Code)
	}
	pool.Exec(ctx, `UPDATE core.orgs SET suspended_at = NULL WHERE id::text = $1`, orgID)

	h.counts = map[string]int{key.ID: perMinute}
	h.window = time.Now()
	if w := get("/public/catalog?key="+key.Key, ""); w.Code != 429 {
		t.Fatalf("over the limit: %d", w.Code)
	}
	h.counts = nil

	r := httptest.NewRequest("DELETE", "/orgs/shop-keys/"+key.ID, nil)
	r.SetPathValue("id", key.ID)
	r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: "admin"}))
	rw := httptest.NewRecorder()
	h.Revoke(rw, r)
	if rw.Code != 204 {
		t.Fatalf("revoke: %d", rw.Code)
	}
	if w := get("/public/catalog?key="+key.Key, ""); w.Code != 401 {
		t.Fatalf("revoked key still works: %d", w.Code)
	}
}
