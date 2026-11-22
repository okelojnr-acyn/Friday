package auth

// Friday Host SSO exchange against a real Postgres.

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSsoExchange(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	h.Issuer = NewIssuer("test-secret-test-secret-test-secret", time.Hour)
	ctx := context.Background()
	orgID := newOrg(t, pool)
	email := "owner-" + randHex(4) + "@example.com"
	ownerID, err := h.joinOrg(ctx, email, "Owner", orgID, "owner")
	if err != nil {
		t.Fatal(err)
	}

	// Host's token: a Host account id, the same email in another case, Host's role.
	host := &Claims{OrgID: orgID, Role: "admin", Email: strings.ToUpper(email)}
	host.Subject = "30cd17cc-ce2a-4b95-a93f-82bf58b2d570"
	w := doJSON(t, h.SsoExchange, "POST", "/auth/sso", host, nil, nil, nil)
	if w.Code != 200 {
		t.Fatalf("exchange: %d %s", w.Code, w.Body)
	}
	var got authResponse
	json.NewDecoder(w.Body).Decode(&got)
	c, err := h.Issuer.Verify(got.Token)
	if err != nil || c.Subject != ownerID || c.Role != "owner" || c.OrgID != orgID {
		t.Fatalf("want the Friday owner, got %+v %v", c, err)
	}

	// No member with that email: refused, never created.
	stranger := &Claims{OrgID: orgID, Role: "owner", Email: "nobody-" + randHex(4) + "@example.com"}
	stranger.Subject = host.Subject
	if w := doJSON(t, h.SsoExchange, "POST", "/auth/sso", stranger, nil, nil, nil); w.Code != 403 {
		t.Fatalf("stranger: %d %s", w.Code, w.Body)
	}

	// An assistant's token can't be exchanged.
	guss := &Claims{OrgID: orgID, Role: "owner", Email: email, Via: "guss"}
	guss.Subject = ownerID
	if w := doJSON(t, h.SsoExchange, "POST", "/auth/sso", guss, nil, nil, nil); w.Code != 401 {
		t.Fatalf("via token: %d", w.Code)
	}
}
