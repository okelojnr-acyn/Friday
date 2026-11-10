package gateway

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// Regression for 2026-11-10: crm/invoicing answered with a stale
// Access-Control-Allow-Origin from their own env, and the browser dropped
// every response. The proxy must strip app-sent CORS headers so the
// kernel's withCORS is the only source.
func TestAppProxyStripsUpstreamCORS(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/opportunities" {
			t.Errorf("upstream path = %q, want /opportunities", r.URL.Path)
		}
		w.Header().Set("Access-Control-Allow-Origin", "https://stale.example")
		w.Header().Set("Access-Control-Allow-Credentials", "true")
		w.Header().Set("X-App", "crm")
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	proxy, err := NewAppProxy(registry.App{Name: "crm", BaseURL: upstream.URL})
	if err != nil {
		t.Fatal(err)
	}
	rec := httptest.NewRecorder()
	rec.Header().Set("Access-Control-Allow-Origin", "https://friday.example") // as withCORS would
	proxy.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/crm/opportunities", nil))

	got := rec.Header().Values("Access-Control-Allow-Origin")
	if len(got) != 1 || got[0] != "https://friday.example" {
		t.Fatalf("Access-Control-Allow-Origin = %v, want exactly the kernel's origin", got)
	}
	if rec.Header().Get("Access-Control-Allow-Credentials") != "" {
		t.Fatal("upstream Access-Control-Allow-Credentials leaked through")
	}
	if rec.Header().Get("X-App") != "crm" {
		t.Fatal("non-CORS upstream headers must still pass through")
	}
}
