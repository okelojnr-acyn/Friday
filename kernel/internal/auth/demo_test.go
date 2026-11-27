package auth

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestParseDemoUsers(t *testing.T) {
	got := ParseDemoUsers(" owner=o@demo.test , cashier=c@demo.test,bad,=x@y, nope=no-at")
	if len(got) != 2 || got["owner"] != "o@demo.test" || got["cashier"] != "c@demo.test" {
		t.Fatalf("%v", got)
	}
	if len(ParseDemoUsers("")) != 0 {
		t.Fatal("no demo users on a real Friday")
	}
}

// The demo refuses what could reach the outside world; a real Friday
// refuses nothing extra.
func TestDemoGuard(t *testing.T) {
	ok := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusTeapot) })
	demo := DemoGuard(map[string]string{"owner": "o@demo.test"}, ok)
	real := DemoGuard(nil, ok)
	for _, c := range []struct {
		method, path string
		refused      bool
	}{
		{"PUT", "/orgs/integrations/paystack", true},
		{"GET", "/orgs/integrations", false},
		{"POST", "/orgs/invites", true},
		{"POST", "/invites/abc/accept", true},
		{"POST", "/auth/register", true},
		{"POST", "/guss/link", true},
		{"POST", "/api/invoicing/pos/sales", false},
		{"PATCH", "/api/inventory/products/1", false},
	} {
		rec := httptest.NewRecorder()
		demo.ServeHTTP(rec, httptest.NewRequest(c.method, c.path, nil))
		if (rec.Code == http.StatusForbidden) != c.refused {
			t.Errorf("demo %s %s: %d", c.method, c.path, rec.Code)
		}
		rec = httptest.NewRecorder()
		real.ServeHTTP(rec, httptest.NewRequest(c.method, c.path, nil))
		if rec.Code != http.StatusTeapot {
			t.Errorf("a real Friday refused %s %s", c.method, c.path)
		}
	}
}
