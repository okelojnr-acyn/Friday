package auth

// The supplier page's sign-in against a real Postgres (plan 12.6).

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSupplierLinkCodeAndSession(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	h.Issuer = NewIssuer("test-secret-test-secret-test-secret", time.Hour)
	h.Otp = &OtpStore{Pool: pool}
	h.WebURL = "https://friday.example"
	ctx := context.Background()
	orgID := newOrg(t, pool)
	ownerEmail := "owner-" + randHex(4) + "@example.com"
	ownerID, err := h.joinOrg(ctx, ownerEmail, "Owner", orgID, "owner")
	if err != nil {
		t.Fatal(err)
	}
	owner := claimsFor(ownerID, orgID, ownerEmail)
	supplierID := "5b0c1f0e-1c2d-4e5f-8a9b-" + randHex(6)
	supplierEmail := "sales-" + randHex(4) + "@acme.example"

	// A cashier (no purchasing) can't share; the owner can.
	cashier := &Claims{OrgID: orgID, Role: "member", Email: "c@x"}
	cashier.Subject = ownerID
	body := map[string]string{"supplier_id": supplierID, "supplier_name": "Acme", "email": supplierEmail}
	if w := doJSON(t, h.CreateSupplierLink, "POST", "/orgs/supplier-links", cashier, nil, body, nil); w.Code != 403 {
		t.Fatalf("cashier: %d", w.Code)
	}
	newLink := func() string {
		w := doJSON(t, h.CreateSupplierLink, "POST", "/orgs/supplier-links", owner, nil, body, nil)
		var out struct {
			Link string `json:"link"`
		}
		json.NewDecoder(w.Body).Decode(&out)
		if w.Code != 201 || !strings.HasPrefix(out.Link, "https://friday.example/supplier?t=") {
			t.Fatalf("link: %d %s", w.Code, out.Link)
		}
		return strings.TrimPrefix(out.Link, "https://friday.example/supplier?t=")
	}
	old := newLink()
	tok := newLink() // replaces the first

	if w := doJSON(t, h.SupplierCode, "POST", "/supplier/code", nil, nil, map[string]string{"t": old}, nil); w.Code != 404 {
		t.Fatalf("replaced link: %d", w.Code)
	}
	w := doJSON(t, h.SupplierCode, "POST", "/supplier/code", nil, nil, map[string]string{"t": tok}, nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"email_hint":"s***@acme.example"`) {
		t.Fatalf("code: %d %s", w.Code, w.Body)
	}
	// The emailed code (no mailer in tests): set a known one.
	if _, err := pool.Exec(ctx, `UPDATE core.otp_codes SET code_hash = $1 WHERE email = $2`,
		hashOtp(supplierEmail, "123456"), strings.ToLower(supplierEmail)); err != nil {
		t.Fatal(err)
	}
	if w := doJSON(t, h.SupplierVerify, "POST", "/supplier/verify", nil, nil, map[string]string{"t": tok, "code": "000000"}, nil); w.Code != 401 {
		t.Fatalf("wrong code: %d", w.Code)
	}
	w = doJSON(t, h.SupplierVerify, "POST", "/supplier/verify", nil, nil, map[string]string{"t": tok, "code": "123456"}, nil)
	var session struct {
		Token string `json:"token"`
	}
	json.NewDecoder(w.Body).Decode(&session)
	if w.Code != 200 {
		t.Fatalf("verify: %d", w.Code)
	}
	c, err := h.Issuer.Verify(session.Token)
	if err != nil || c.Via != SupplierVia || c.Subject != "supplier:"+supplierID || c.OrgID != orgID || c.Access["inventory"] != "write" || len(c.Perms) != 0 {
		t.Fatalf("session: %+v %v", c, err)
	}
}
