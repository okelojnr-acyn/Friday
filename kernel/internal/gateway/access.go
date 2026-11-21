package gateway

import (
	"encoding/json"
	"net/http"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// EnforceAccess limits an assistant's token (claims.Via set, e.g. Guss
// acting for a linked user) to what the org allowed for this app: "read"
// lets GET/HEAD through, "write" lets everything through, anything else
// is refused. A viewer's session may only read, in every app. Other
// user sessions pass; their role is checked by the app as always.
func EnforceAccess(app string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		claims, ok := auth.FromContext(r.Context())
		need := "write"
		if r.Method == http.MethodGet || r.Method == http.MethodHead {
			need = "read"
		}
		// A viewer reads, whatever the app does: found 2026-11-22, no app
		// checked it, so viewers could create invoices and edit stock.
		if ok && claims.Role == "viewer" && need == "write" {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]string{"error": "view-only members can't change anything; ask an admin"})
			return
		}
		if !ok || claims.Via == "" {
			next.ServeHTTP(w, r)
			return
		}
		if !Allows(claims.Access[app], need) {
			msg := claims.Via + " has no " + need + " access to " + app +
				" (an admin sets it in Friday: Integrations, Guss)"
			if claims.Via == auth.PosVia {
				msg = "a cashier PIN sign-in only reaches the till; clock in with your fingerprint for this"
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]string{"error": msg})
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Allows reports whether access level `have` covers `need` ("read" or
// "write").
func Allows(have, need string) bool {
	switch have {
	case "write":
		return true
	case "read":
		return need == "read"
	default:
		return false
	}
}
