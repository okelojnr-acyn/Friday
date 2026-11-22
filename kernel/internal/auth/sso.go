package auth

import (
	"errors"
	"log"
	"net/http"

	"github.com/jackc/pgx/v5"
)

// SsoExchange (POST /auth/sso): Friday Host's "Open Friday" signs a token
// whose subject is the person's Friday Host account, not their Friday
// user, so anything that stores "who" (Guss links, POS PINs) pointed at
// nobody. Friday's /sso page trades it here for a session as the Friday
// member with the same email, with their Friday role.
func (h *Handlers) SsoExchange(w http.ResponseWriter, r *http.Request) {
	c, ok := FromContext(r.Context())
	if !ok || c.Via != "" {
		writeError(w, http.StatusUnauthorized, "sign in again from Friday Host")
		return
	}
	var userID, email, role string
	err := h.Pool.QueryRow(r.Context(), `
		SELECT u.id::text, u.email, m.role FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE m.org_id::text = $1 AND (u.id::text = $2 OR lower(u.email) = lower($3))
		ORDER BY (u.id::text = $2) DESC LIMIT 1`, c.OrgID, c.Subject, c.Email).Scan(&userID, &email, &role)
	if errors.Is(err, pgx.ErrNoRows) {
		// No auto-create: a removed member's unexpired token would bring them back.
		writeError(w, http.StatusForbidden, "no one with this email is a member here; ask the owner to invite you")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	token, err := h.Issuer.Issue(userID, c.OrgID, role, email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	if userID != c.Subject {
		log.Printf("sso: org %s, host account %s signed in as member %s", c.OrgID, c.Subject, userID)
	}
	writeJSON(w, http.StatusOK, authResponse{Token: token, OrgID: c.OrgID, Role: role, Email: email})
}
