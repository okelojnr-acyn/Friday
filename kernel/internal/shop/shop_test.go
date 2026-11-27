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
	if w := get("/public/catalog", ""); w.Code != 401 || w.Header().Get("Access-Control-Allow-Origin") != "*" {
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
	// Refused, but readable there (an error holds no shop data).
	if w := get("/public/catalog?key="+key.Key, "https://elsewhere.example"); w.Code != 403 || w.Header().Get("Access-Control-Allow-Origin") != "*" {
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

func TestShopQuoteOrderAndTrack(t *testing.T) {
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
	pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug, currency) VALUES ('Duka', $1, 'KES') RETURNING id::text`,
		fmt.Sprintf("duka2-%d", time.Now().UnixNano())).Scan(&orgID)
	key := "fpk_" + strings.Repeat("a", 30) + fmt.Sprint(time.Now().UnixNano()%1e9)
	pool.Exec(ctx, `INSERT INTO core.shop_keys (org_id, name, key) VALUES ($1::uuid, 'Web', $2)`, orgID, key)

	var gotBody string
	inventory := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b := new(bytes.Buffer)
		b.ReadFrom(r.Body)
		gotBody = b.String()
		switch {
		case r.Method == "POST" && r.URL.Path == "/shop/quote":
			if r.Header.Get("Content-Type") != "application/json" {
				w.WriteHeader(415)
				return
			}
			w.Write([]byte(`{"lines":[],"total_cents":70000,"problems":[]}`))
		case r.Method == "POST" && r.URL.Path == "/shop/orders":
			w.WriteHeader(409)
			w.Write([]byte(`{"detail":{"message":"some items can't be ordered","problems":[{"product_id":"p1","reason":"not enough in stock"}]}}`))
		case r.URL.Path == "/shop/orders/11111111-2222-3333-4444-555555555555" && r.URL.Query().Get("token") == "tok":
			w.Write([]byte(`{"number":"W1","status":"placed"}`))
		default:
			w.WriteHeader(404)
			w.Write([]byte(`{"detail":"order not found"}`))
		}
	}))
	defer inventory.Close()
	h := &Handlers{Pool: pool, Issuer: auth.NewIssuer(strings.Repeat("s", 32), time.Hour), InventoryURL: inventory.URL}
	call := func(hf http.HandlerFunc, method, path, body string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "text/plain") // a page skipping the preflight
		if i := strings.Index(path, "/public/orders/"); i >= 0 {
			r.SetPathValue("id", strings.SplitN(path[i+len("/public/orders/"):], "?", 2)[0])
		}
		w := httptest.NewRecorder()
		hf(w, r)
		return w
	}

	w := call(h.Quote, "POST", "/public/quote?key="+key, `{"lines":[{"product_id":"p1","quantity":2}]}`)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"currency":"KES"`) || !strings.Contains(gotBody, `"quantity":2`) {
		t.Fatalf("quote: %d %s (inventory got %s)", w.Code, w.Body, gotBody)
	}
	if w := call(h.Quote, "POST", "/public/quote?key="+key, `not json`); w.Code != 400 {
		t.Fatalf("bad body: %d", w.Code)
	}
	w = call(h.PlaceOrder, "POST", "/public/orders?key="+key, `{"lines":[]}`)
	if w.Code != 409 || !strings.Contains(w.Body.String(), `"reason":"not enough in stock"`) || !strings.Contains(w.Body.String(), `"error":"some items can't be ordered"`) {
		t.Fatalf("refused order: %d %s", w.Code, w.Body)
	}
	w = call(h.Track, "GET", "/public/orders/11111111-2222-3333-4444-555555555555?key="+key+"&token=tok", "")
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" || !strings.Contains(w.Body.String(), `"number":"W1"`) {
		t.Fatalf("track: %d %s", w.Code, w.Body)
	}
	if w := call(h.Track, "GET", "/public/orders/11111111-2222-3333-4444-555555555555?key="+key+"&token=nope", ""); w.Code != 404 {
		t.Fatalf("wrong token: %d", w.Code)
	}
	for i := 0; i < orderPerMinute-1; i++ {
		call(h.PlaceOrder, "POST", "/public/orders?key="+key, `{}`)
	}
	if w := call(h.PlaceOrder, "POST", "/public/orders?key="+key, `{}`); w.Code != 429 {
		t.Fatalf("order flood not limited: %d", w.Code)
	}
}

func TestShopPayUsesTheStoredOrder(t *testing.T) {
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
	n := time.Now().UnixNano()
	var orgID, userID string
	pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug, currency) VALUES ('Duka', $1, 'KES') RETURNING id::text`, fmt.Sprintf("duka3-%d", n)).Scan(&orgID)
	pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES ($1) RETURNING id::text`, fmt.Sprintf("owner%d@duka.test", n)).Scan(&userID)
	pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1::uuid, $2::uuid, 'owner')`, orgID, userID)
	key := fmt.Sprintf("fpk_pay%d", n)
	pool.Exec(ctx, `INSERT INTO core.shop_keys (org_id, name, key) VALUES ($1::uuid, 'Web', $2)`, orgID, key)

	status := "placed"
	inventory := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/shop/orders/11111111-2222-3333-4444-555555555555/checkout" && r.URL.Query().Get("token") == "tok" {
			fmt.Fprintf(w, `{"number":"W1","status":%q,"total_cents":70000,"email":"","lines":[{"product_id":"p1","quantity":2,"unit_price_cents":35000}]}`, status)
			return
		}
		w.WriteHeader(404)
		w.Write([]byte(`{"detail":"order not found"}`))
	}))
	defer inventory.Close()
	var sent map[string]any
	invoicing := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&sent)
		w.WriteHeader(201)
		w.Write([]byte(`{"redirect_url":"https://checkout.paystack.com/x","invoice_number":"WEB-W1"}`))
	}))
	defer invoicing.Close()
	h := &Handlers{Pool: pool, Issuer: auth.NewIssuer(strings.Repeat("s", 32), time.Hour), InventoryURL: inventory.URL, InvoicingURL: invoicing.URL}
	pay := func(token string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/public/orders/x/pay?key="+key+"&token="+token, strings.NewReader(`{"total_cents":1,"lines":[]}`))
		r.SetPathValue("id", "11111111-2222-3333-4444-555555555555")
		w := httptest.NewRecorder()
		h.Pay(w, r)
		return w
	}
	w := pay("tok")
	if w.Code != 201 || !strings.Contains(w.Body.String(), "checkout.paystack.com") {
		t.Fatalf("pay: %d %s", w.Code, w.Body)
	}
	if sent["total_cents"] != float64(70000) || sent["currency"] != "KES" || sent["fallback_email"] != fmt.Sprintf("owner%d@duka.test", n) ||
		sent["order_id"] != "11111111-2222-3333-4444-555555555555" || len(sent["lines"].([]any)) != 1 {
		t.Fatalf("Invoicing got %v (the page's body must be ignored)", sent)
	}
	if w := pay("wrong"); w.Code != 404 {
		t.Fatalf("wrong token: %d", w.Code)
	}
	status = "paid"
	if w := pay("tok"); w.Code != 409 {
		t.Fatalf("paid order paid again: %d", w.Code)
	}
}
