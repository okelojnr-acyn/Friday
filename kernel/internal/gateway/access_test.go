package gateway

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

func TestAllows(t *testing.T) {
	cases := []struct {
		have, need string
		want       bool
	}{
		{"write", "write", true}, {"write", "read", true},
		{"read", "read", true}, {"read", "write", false},
		{"none", "read", false}, {"", "read", false},
	}
	for _, c := range cases {
		if got := Allows(c.have, c.need); got != c.want {
			t.Errorf("Allows(%q, %q) = %v, want %v", c.have, c.need, got, c.want)
		}
	}
}

func TestEnforceAccess(t *testing.T) {
	ok := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusTeapot) })
	run := func(claims *auth.Claims, app, method string) int {
		r := httptest.NewRequest(method, "/api/"+app+"/products", nil)
		if claims != nil {
			r = r.WithContext(auth.WithClaims(r.Context(), claims))
		}
		w := httptest.NewRecorder()
		EnforceAccess(app, ok).ServeHTTP(w, r)
		return w.Code
	}
	user := &auth.Claims{Role: "member"}
	guss := &auth.Claims{Role: "owner", Via: "guss", Access: map[string]string{"inventory": "write", "invoicing": "read"}}

	if got := run(user, "accounting", http.MethodPost); got != http.StatusTeapot {
		t.Errorf("a user session must pass untouched, got %d", got)
	}
	if got := run(guss, "inventory", http.MethodPost); got != http.StatusTeapot {
		t.Errorf("write access allows POST, got %d", got)
	}
	if got := run(guss, "invoicing", http.MethodGet); got != http.StatusTeapot {
		t.Errorf("read access allows GET, got %d", got)
	}
	if got := run(guss, "invoicing", http.MethodPost); got != http.StatusForbidden {
		t.Errorf("read access refuses POST, got %d", got)
	}
	if got := run(guss, "accounting", http.MethodGet); got != http.StatusForbidden {
		t.Errorf("no access refuses even GET, got %d", got)
	}
}
