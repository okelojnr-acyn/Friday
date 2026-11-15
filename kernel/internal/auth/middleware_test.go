package auth

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestAssistantTokensOnlyReachAppRoutes(t *testing.T) {
	iss := NewIssuer("secret", time.Hour)
	token, err := iss.IssueVia("u1", "o1", "owner", "a@b.c", "guss", map[string]string{"inventory": "read"}, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusTeapot) })
	for path, want := range map[string]int{
		"/api/inventory/products":        http.StatusTeapot,
		"/orgs/members/u2/role":          http.StatusForbidden,
		"/orgs/integrations/guss":        http.StatusForbidden,
		"/auth/passkey/register-options": http.StatusForbidden,
	} {
		r := httptest.NewRequest(http.MethodGet, path, nil)
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		RequireAuth(iss)(next).ServeHTTP(w, r)
		if w.Code != want {
			t.Errorf("%s: got %d, want %d", path, w.Code, want)
		}
	}

	claims, err := iss.Verify(token)
	if err != nil || claims.Via != "guss" || claims.Access["inventory"] != "read" {
		t.Fatalf("claims round trip: %+v %v", claims, err)
	}
}
