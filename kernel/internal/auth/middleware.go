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
			ctx := WithClaims(r.Context(), claims)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
