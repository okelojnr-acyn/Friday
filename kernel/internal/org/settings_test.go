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
	// Payment methods: all by default; a business narrows them; unknown or none is refused.
	if got := v["payment_methods"].([]any); len(got) != len(PaymentMethods) {
		t.Fatalf("default methods: %v", got)
	}
	code, v = call(http.MethodPut, "admin", "", `{"payment_methods":["cash","Paystack","cash"]}`)
	if got, _ := json.Marshal(v["payment_methods"]); code != 200 || string(got) != `["cash","paystack"]` {
		t.Fatalf("methods: %d %s", code, got)
	}
	for _, bad := range []string{`{"payment_methods":["bitcoin"]}`, `{"payment_methods":[]}`} {
		if code, _ := call(http.MethodPut, "admin", "", bad); code != http.StatusBadRequest {
			t.Fatalf("%s: %d", bad, code)
		}
	}
	if code, v = call(http.MethodPut, "admin", "", `{"currency":"KES"}`); len(v["payment_methods"].([]any)) != 2 {
		t.Fatalf("methods kept: %d %v", code, v)
	}
}

func TestTaxProfileDrivesTheTillRateAndEtimsHidesTheKey(t *testing.T) {
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
	e := &Etims{Pool: pool, InternalToken: "tok", Automation: true}
	manual := &Etims{Pool: pool}
	call := func(h func(http.ResponseWriter, *http.Request), method, role, body string) (int, map[string]any) {
		r := httptest.NewRequest(method, "/", bytes.NewBufferString(body))
		r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: role, RegisteredClaims: jwt.RegisteredClaims{Subject: "u"}}))
		w := httptest.NewRecorder()
		h(w, r)
		var out map[string]any
		json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}

	// An org saved before tax_profile existed reads the Kenyan defaults.
	_, v := call(s.Get, http.MethodGet, "member", "")
	tax := v["tax"].(map[string]any)
	if tax["default_code"] != "B" || len(tax["rates"].([]any)) != 5 || tax["vat_registered"] != true {
		t.Fatalf("default tax profile: %v", tax)
	}

	rates := `[{"code":"A","name":"Exempt","rate_bp":0},{"code":"B","name":"Standard VAT","rate_bp":1600},{"code":"E","name":"Reduced VAT","rate_bp":800}]`
	if code, out := call(s.Put, http.MethodPut, "owner", `{"tax":{"vat_registered":true,"tax_pin":"","default_code":"B","rates":`+rates+`}}`); code != 400 {
		t.Fatalf("VAT-registered without a PIN: %d %v", code, out)
	}
	if code, _ := call(s.Put, http.MethodPut, "owner", `{"tax":{"vat_registered":true,"tax_pin":"12345","default_code":"B","rates":`+rates+`}}`); code != 400 {
		t.Fatalf("not a KRA PIN: %d", code)
	}
	if code, _ := call(s.Put, http.MethodPut, "owner", `{"tax":{"vat_registered":true,"tax_pin":"P051234567X","default_code":"Z","rates":`+rates+`}}`); code != 400 {
		t.Fatalf("unknown default code: %d", code)
	}
	code, v := call(s.Put, http.MethodPut, "owner", `{"tax":{"vat_registered":true,"tax_pin":"p051234567x","default_code":"E","rates":`+rates+`,"receipt_footer":" Asante "}}`)
	if code != 200 || v["tax_rate_bp"] != float64(800) || v["tax"].(map[string]any)["tax_pin"] != "P051234567X" || v["tax"].(map[string]any)["receipt_footer"] != "Asante" {
		t.Fatalf("save tax: %d %v", code, v)
	}
	code, v = call(s.Put, http.MethodPut, "owner", `{"tax":{"vat_registered":false,"tax_pin":"P051234567X","default_code":"B","rates":`+rates+`}}`)
	if code != 200 || v["tax_rate_bp"] != float64(0) {
		t.Fatalf("not VAT-registered charges no VAT: %d %v", code, v)
	}

	// eTIMS: owners and admins only; the CMC key is stored, never returned.
	if code, _ := call(e.Get, http.MethodGet, "member", ""); code != http.StatusForbidden {
		t.Fatalf("member reads eTIMS: %d", code)
	}
	code, v = call(e.Get, http.MethodGet, "admin", "")
	if code != 200 || v["mode"] != "oscu" || v["branch_id"] != "00" || v["enabled"] != false {
		t.Fatalf("eTIMS defaults: %d %v", code, v)
	}
	if code, _ := call(e.Put, http.MethodPut, "owner", `{"enabled":true}`); code != 400 {
		t.Fatalf("enabled without a device serial: %d", code)
	}
	if code, _ := call(e.Put, http.MethodPut, "owner", `{"branch_id":"1"}`); code != 400 {
		t.Fatalf("one-digit branch: %d", code)
	}
	// Until the server allows automation, sales are filed by hand.
	if code, _ := call(manual.Put, http.MethodPut, "owner", `{"enabled":true,"device_serial":"KRA-001"}`); code != 400 {
		t.Fatalf("enabled without automation: %d", code)
	}
	code, v = call(e.Put, http.MethodPut, "owner", `{"enabled":true,"device_serial":"KRA-001","cmc_key":"secret-cmc"}`)
	if code != 200 || v["cmc_key_set"] != true || v["enabled"] != true {
		t.Fatalf("save eTIMS: %d %v", code, v)
	}
	if _, ok := v["cmc_key"]; ok {
		t.Fatal("the CMC key was sent back")
	}
	// Saving other fields keeps the key.
	code, v = call(e.Put, http.MethodPut, "owner", `{"environment":"production"}`)
	if code != 200 || v["cmc_key_set"] != true || v["environment"] != "production" {
		t.Fatalf("keep key: %d %v", code, v)
	}
	var stored string
	pool.QueryRow(ctx, `SELECT cmc_key FROM core.org_etims WHERE org_id = $1`, orgID).Scan(&stored)
	if stored != "secret-cmc" {
		t.Fatal("CMC key not stored")
	}
	// Friday's own apps read the key with the internal token only.
	internal := func(token string) (int, map[string]any) {
		r := httptest.NewRequest(http.MethodGet, "/internal/etims/"+orgID, nil)
		r.SetPathValue("org_id", orgID)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		w := httptest.NewRecorder()
		e.GetInternal(w, r)
		var out map[string]any
		json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}
	if code, _ := internal("wrong"); code != http.StatusUnauthorized {
		t.Fatalf("internal with a wrong token: %d", code)
	}
	if code, out := internal("tok"); code != 200 || out["cmc_key"] != "secret-cmc" || out["tax_pin"] != "P051234567X" {
		t.Fatalf("internal: %d %v", code, out)
	}
	code, v = call(e.Put, http.MethodPut, "owner", `{"clear_cmc_key":true}`)
	if code != 200 || v["cmc_key_set"] != false {
		t.Fatalf("clear key: %d %v", code, v)
	}
}
