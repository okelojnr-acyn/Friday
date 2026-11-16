package auth

import (
	"net/http"
	"strings"
)

// RequireAuth verifies the bearer token and stores the claims on the
// request context. The same verified claims are what gets forwarded
// downstream to app services (as the same JWT, re-verified independently
// by friday_common.auth) -- the kernel doesn't translate identity into a
// different format per hop.
func RequireAuth(issuer *Issuer) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			header := r.Header.Get("Authorization")
			if !strings.HasPrefix(header, "Bearer ") {
				writeError(w, http.StatusUnauthorized, "missing bearer token")
				return
			}
			token := strings.TrimPrefix(header, "Bearer ")
			claims, err := issuer.Verify(token)
			if err != nil {
				writeError(w, http.StatusUnauthorized, "invalid token: "+err.Error())
				return
			}
			// An assistant's token works on app routes only, never on the
			// kernel's own (members, roles, integrations, passkeys).
			if claims.Via != "" && !strings.HasPrefix(r.URL.Path, "/api/") && !posKernelRoute(claims.Via, r) {
				writeError(w, http.StatusForbidden, claims.Via+" tokens only reach app routes")
				return
			}
			ctx := WithClaims(r.Context(), claims)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// posKernelRoute lets a cashier's PIN session read the two kernel routes
// the till itself needs: who is signed in, and the org's settings
// (currency, receipt details).
func posKernelRoute(via string, r *http.Request) bool {
	if via != PosVia || r.Method != http.MethodGet {
		return false
	}
	return r.URL.Path == "/auth/me" || r.URL.Path == "/orgs/settings"
}
