package guss

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestValidURL(t *testing.T) {
	for raw, ok := range map[string]bool{
		"https://shop-guss.tenants.fridayhost.dev":   true,
		"https://shop-guss.tenants.fridayhost.dev/ ": true,
		"http://shop-guss.tenants.fridayhost.dev":    false,
		"https://user:pw@host.example":               false,
		"file:///etc/passwd":                         false,
		"":                                           false,
	} {
		if _, err := validURL(raw); (err == nil) != ok {
			t.Errorf("validURL(%q) err=%v, want ok=%v", raw, err, ok)
		}
	}
}

func TestBlockPrivate(t *testing.T) {
	for addr, blocked := range map[string]bool{
		"127.0.0.1:443":      true,
		"10.1.2.3:443":       true,
		"172.18.0.5:8081":    true,
		"192.168.1.1:443":    true,
		"169.254.169.254:80": true,
		"[::1]:443":          true,
		"[fd00::1]:443":      true,
		"0.0.0.0:443":        true,
		"2.28.133.174:443":   false,
		"[2a01:4f8::1]:443":  false,
	} {
		if err := blockPrivate("tcp", addr, nil); (err != nil) != blocked {
			t.Errorf("blockPrivate(%s) err=%v, want blocked=%v", addr, err, blocked)
		}
	}
}

// The default client really refuses a loopback server even when the URL
// itself looks fine.
func TestDefaultClientRefusesLoopback(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Fatal("request reached a loopback server")
	}))
	defer srv.Close()
	h := &Handlers{}
	_, status, err := h.call(context.Background(), config{URL: srv.URL, Token: "t"}, http.MethodGet, "/api/report?window=day", nil)
	if err == nil || status != http.StatusFailedDependency {
		t.Fatalf("status=%d err=%v", status, err)
	}
}

func TestCallForwardsTokenAndMapsErrors(t *testing.T) {
	var gotAuth, gotBody string
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		var b map[string]string
		json.NewDecoder(r.Body).Decode(&b)
		gotBody = b["conversation_id"] + "|" + b["text"]
		switch b["text"] {
		case "bad-token":
			w.WriteHeader(http.StatusUnauthorized)
		case "busy":
			w.WriteHeader(http.StatusTooManyRequests)
			json.NewEncoder(w).Encode(map[string]string{"error": "Guss is busy"})
		default:
			json.NewEncoder(w).Encode(map[string]string{"reply": "Recorded: 2 x soap"})
		}
	}))
	defer srv.Close()
	h := &Handlers{Client: srv.Client()}
	c := config{URL: srv.URL, Token: "secret-token"}

	reply, status, err := h.call(context.Background(), c, http.MethodPost, "/api/chat",
		map[string]string{"conversation_id": "friday:u1", "text": "sold 2 soap"})
	if err != nil || status != 200 || reply != "Recorded: 2 x soap" {
		t.Fatalf("reply=%q status=%d err=%v", reply, status, err)
	}
	if gotAuth != "Bearer secret-token" || gotBody != "friday:u1|sold 2 soap" {
		t.Fatalf("auth=%q body=%q", gotAuth, gotBody)
	}
	if _, status, err = h.call(context.Background(), c, http.MethodPost, "/api/chat",
		map[string]string{"conversation_id": "x", "text": "bad-token"}); err == nil ||
		status != http.StatusFailedDependency || !strings.Contains(err.Error(), "token") {
		t.Fatalf("bad token: status=%d err=%v", status, err)
	}
	if _, status, err = h.call(context.Background(), c, http.MethodPost, "/api/chat",
		map[string]string{"conversation_id": "x", "text": "busy"}); err == nil ||
		status != http.StatusTooManyRequests || err.Error() != "Guss is busy" {
		t.Fatalf("busy: status=%d err=%v", status, err)
	}
}
