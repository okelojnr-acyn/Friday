package auth

// Cashier PIN against a real Postgres (plan section 11).

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func doJSON(t *testing.T, h http.HandlerFunc, method, path string, claims *Claims, headers map[string]string, body any, pathValues map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, path, &buf)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	for k, v := range pathValues {
		req.SetPathValue(k, v)
	}
	if claims != nil {
		req = req.WithContext(WithClaims(req.Context(), claims))
	}
	w := httptest.NewRecorder()
	h(w, req)
	return w
}

func TestCashierPin(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	h.Issuer = NewIssuer("test-secret-test-secret-test-secret", time.Hour)
	ctx := context.Background()
	orgID := newOrg(t, pool)
	ownerEmail := "owner-" + randHex(4) + "@example.com"
	ownerID, err := h.joinOrg(ctx, ownerEmail, "Owner", orgID, "owner")
	if err != nil {
		t.Fatal(err)
	}
	owner := claimsFor(ownerID, orgID, ownerEmail)
	cashierEmail := "cashier-" + randHex(4) + "@example.com"
	cashierID, err := h.joinOrg(ctx, cashierEmail, "Cashier", orgID, "member")
	if err != nil {
		t.Fatal(err)
	}
	cashier := &Claims{OrgID: orgID, Role: "member", Email: cashierEmail}
	cashier.Subject = cashierID

	// Setting a PIN: weak or short ones are refused; a cashier can't enrol tills.
	if w := doJSON(t, h.SetPosPin, "PUT", "/pos/pin", cashier, nil, map[string]string{"pin": "123456"}, nil); w.Code != 400 {
		t.Fatalf("weak PIN: %d %s", w.Code, w.Body)
	}
	if w := doJSON(t, h.SetPosPin, "PUT", "/pos/pin", cashier, nil, map[string]string{"pin": "48213"}, nil); w.Code != 400 {
		t.Fatalf("short PIN: %d", w.Code)
	}
	if w := doJSON(t, h.SetPosPin, "PUT", "/pos/pin", cashier, nil, map[string]string{"pin": "482913"}, nil); w.Code != 204 {
		t.Fatalf("set PIN: %d %s", w.Code, w.Body)
	}
	if w := doJSON(t, h.EnrolPosDevice, "POST", "/pos/devices", cashier, nil, map[string]string{"name": "Till 1"}, nil); w.Code != 403 {
		t.Fatalf("cashier enrolling a till: %d", w.Code)
	}

	login := func(device, userID, pin string) *httptest.ResponseRecorder {
		hd := map[string]string{}
		if device != "" {
			hd[PosDeviceHeader] = device
		}
		return doJSON(t, h.PosPinLogin, "POST", "/auth/pos/pin", nil, hd, map[string]string{"user_id": userID, "pin": pin}, nil)
	}

	// PIN on an un-enrolled device is refused.
	if w := login("", cashierID, "482913"); w.Code != 403 {
		t.Fatalf("no device: %d", w.Code)
	}
	if w := login("made-up-token", cashierID, "482913"); w.Code != 403 {
		t.Fatalf("unknown device: %d", w.Code)
	}

	w := doJSON(t, h.EnrolPosDevice, "POST", "/pos/devices", owner, nil, map[string]string{"name": "Till 1"}, nil)
	if w.Code != 201 {
		t.Fatalf("enrol: %d %s", w.Code, w.Body)
	}
	var dev struct{ ID, Token string }
	json.Unmarshal(w.Body.Bytes(), &dev)

	// The till lists cashiers with a PIN.
	w = doJSON(t, h.PosCashiers, "GET", "/auth/pos/cashiers", nil, map[string]string{PosDeviceHeader: dev.Token}, nil, nil)
	var people []posPerson
	json.Unmarshal(w.Body.Bytes(), &people)
	if w.Code != 200 || len(people) != 1 || people[0].UserID != cashierID {
		t.Fatalf("cashiers: %d %s", w.Code, w.Body)
	}

	// The right PIN gives a POS-only token.
	w = login(dev.Token, cashierID, "482913")
	if w.Code != 200 {
		t.Fatalf("PIN sign-in: %d %s", w.Code, w.Body)
	}
	var resp authResponse
	json.Unmarshal(w.Body.Bytes(), &resp)
	c, err := h.Issuer.Verify(resp.Token)
	if err != nil || c.Via != PosVia || c.Subject != cashierID || c.Access["invoicing"] != "write" || c.Access["inventory"] != "read" || c.Access["accounting"] != "" {
		t.Fatalf("token claims: %+v %v", c, err)
	}

	// A PIN token is refused on kernel routes other than the till's two reads.
	mw := RequireAuth(h.Issuer)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	for _, tc := range []struct {
		method, path string
		want         int
	}{
		{"GET", "/auth/me", 200},
		{"GET", "/orgs/settings", 200},
		{"PUT", "/orgs/settings", 403},
		{"GET", "/orgs/members", 403},
		{"POST", "/pos/devices", 403},
		{"PUT", "/pos/pin", 403},
		{"GET", "/api/invoicing/pos/registers", 200},
	} {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		req.Header.Set("Authorization", "Bearer "+resp.Token)
		rec := httptest.NewRecorder()
		mw.ServeHTTP(rec, req)
		if rec.Code != tc.want {
			t.Fatalf("%s %s with a PIN token: %d, want %d", tc.method, tc.path, rec.Code, tc.want)
		}
	}
	// And the handlers themselves refuse a PIN token for manager work.
	if w := doJSON(t, h.SetPosPin, "PUT", "/pos/pin", c, nil, map[string]string{"pin": "555123"}, nil); w.Code != 403 {
		t.Fatalf("PIN token setting a PIN: %d", w.Code)
	}

	// An owner signing in by PIN is capped at member.
	if w := doJSON(t, h.SetPosPin, "PUT", "/pos/pin", owner, nil, map[string]string{"pin": "730194"}, nil); w.Code != 204 {
		t.Fatalf("owner PIN: %d", w.Code)
	}
	w = login(dev.Token, ownerID, "730194")
	json.Unmarshal(w.Body.Bytes(), &resp)
	if w.Code != 200 || resp.Role != "member" {
		t.Fatalf("owner by PIN: %d role %q", w.Code, resp.Role)
	}

	// Lockout after 5 wrong tries, even with the right PIN after.
	for i := 1; i <= 4; i++ {
		if w := login(dev.Token, cashierID, "000001"); w.Code != 401 {
			t.Fatalf("wrong PIN %d: %d", i, w.Code)
		}
	}
	if w := login(dev.Token, cashierID, "000001"); w.Code != http.StatusLocked {
		t.Fatalf("5th wrong PIN should lock: %d", w.Code)
	}
	if w := login(dev.Token, cashierID, "482913"); w.Code != http.StatusLocked {
		t.Fatalf("right PIN while locked: %d", w.Code)
	}
	// A manager unlocks it.
	if w := doJSON(t, h.UnlockPosPin, "POST", "/pos/pins/x/unlock", owner, nil, nil, map[string]string{"user_id": cashierID}); w.Code != 204 {
		t.Fatalf("unlock: %d %s", w.Code, w.Body)
	}
	if w := login(dev.Token, cashierID, "482913"); w.Code != 200 {
		t.Fatalf("after unlock: %d", w.Code)
	}

	// Revoking the till stops PIN sign-in there.
	if w := doJSON(t, h.RevokePosDevice, "DELETE", "/pos/devices/x", owner, nil, nil, map[string]string{"id": dev.ID}); w.Code != 204 {
		t.Fatalf("revoke: %d", w.Code)
	}
	if w := login(dev.Token, cashierID, "482913"); w.Code != 403 {
		t.Fatalf("revoked till: %d", w.Code)
	}

	// Everything above is in the activity view.
	w = doJSON(t, h.PosPinEvents, "GET", "/pos/pin-events", owner, nil, nil, nil)
	var evs []posPinEvent
	json.Unmarshal(w.Body.Bytes(), &evs)
	kinds := map[string]int{}
	for _, e := range evs {
		kinds[e.Kind]++
	}
	if kinds["signin"] != 3 || kinds["wrong_pin"] != 4 || kinds["locked"] != 1 || kinds["unlocked"] != 1 || kinds["device_enrolled"] != 1 || kinds["device_revoked"] != 1 || kinds["pin_set"] != 2 {
		t.Fatalf("activity: %v", kinds)
	}
}
