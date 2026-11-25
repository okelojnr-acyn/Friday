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
			if claims.Sid != "" && issuer.Sessions != nil && !issuer.Sessions.Active(r.Context(), claims.Sid, claims.Subject) {
				writeError(w, http.StatusUnauthorized, "this device was signed out; sign in again")
				return
			}
			// Their access changed since this token: the app asks for a fresh
			// one (POST /auth/refresh) and tries again.
			if claims.Via == "" && claims.IssuedAt != nil && issuer.Sessions != nil &&
				issuer.Sessions.AccessChangedSince(r.Context(), claims.OrgID, claims.Subject, claims.IssuedAt.Time) {
				writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "your access changed; refreshing", "code": "access_changed"})
				return
			}
			// A supplier reaches only Inventory's supplier routes (their own
			// purchase orders), nothing else in Friday.
			if claims.Via == SupplierVia && !strings.HasPrefix(r.URL.Path, "/api/inventory/supplier/") {
				writeError(w, http.StatusForbidden, "a supplier sign-in only reaches your purchase orders")
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

// posKernelRoute lets a cashier's PIN session reach the kernel routes the
// till itself needs: who is signed in, the org's settings (currency,
// receipt details), and resuming an idle till with the same PIN.
func posKernelRoute(via string, r *http.Request) bool {
	if via != PosVia {
		return false
	}
	if r.Method == http.MethodPost {
		return r.URL.Path == "/auth/pos/resume"
	}
	return r.Method == http.MethodGet && (r.URL.Path == "/auth/me" || r.URL.Path == "/orgs/settings")
}
