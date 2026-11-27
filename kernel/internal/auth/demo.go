package auth

// Demo mode (FRIDAY_DEMO_USERS set, on the demo Friday only): visitors
// try Friday without signing up. "Try as Owner" / "Try as Cashier" gives
// them a session as one of the demo business's people; everything works,
// and the whole business is reset every night (deploy/demo). What could
// reach the outside world is refused here: connecting services (someone
// else's payment or email keys), inviting people (emails) and linking
// Guss. Nothing else differs from a real Friday.

import (
	"encoding/json"
	"errors"
	"net/http"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"
)

// ParseDemoUsers reads "owner=a@x,cashier=b@x" into role -> email.
func ParseDemoUsers(s string) map[string]string {
	out := map[string]string{}
	for _, part := range strings.Split(s, ",") {
		role, email, ok := strings.Cut(strings.TrimSpace(part), "=")
		if ok && role != "" && strings.Contains(email, "@") {
			out[strings.TrimSpace(role)] = strings.TrimSpace(email)
		}
	}
	return out
}

// DemoRoles (GET /auth/demo): the ways in, for the sign-in page. 404 on a
// real Friday, so the page shows its normal sign-in.
func (h *Handlers) DemoRoles(w http.ResponseWriter, r *http.Request) {
	if len(h.Demo) == 0 {
		writeError(w, http.StatusNotFound, "not a demo")
		return
	}
	roles := make([]string, 0, len(h.Demo))
	for role := range h.Demo {
		roles = append(roles, role)
	}
	sort.Strings(roles)
	writeJSON(w, http.StatusOK, map[string]any{"demo": true, "roles": roles})
}

// DemoSignIn (POST /auth/demo {"as": "owner"}): a session as that demo
// person.
func (h *Handlers) DemoSignIn(w http.ResponseWriter, r *http.Request) {
	if len(h.Demo) == 0 {
		writeError(w, http.StatusNotFound, "not a demo")
		return
	}
	var req struct {
		As string `json:"as"`
	}
	json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<10)).Decode(&req)
	email, ok := h.Demo[req.As]
	if !ok {
		writeError(w, http.StatusBadRequest, "choose one of the demo's people")
		return
	}
	var userID string
	err := h.Pool.QueryRow(r.Context(), `SELECT id::text FROM core.users WHERE lower(email) = lower($1)`, email).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusServiceUnavailable, "the demo is being reset; try again in a minute")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	h.issueSessionForUser(w, r, userID, email)
}

// demoRefused: what a demo visitor may not do, with why.
func demoRefused(method, path string) string {
	if method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions {
		return ""
	}
	switch {
	case strings.HasPrefix(path, "/orgs/integrations"):
		return "connecting services is switched off in the demo"
	case strings.HasPrefix(path, "/orgs/invites"), strings.HasPrefix(path, "/invites/"), path == "/auth/register":
		return "inviting people and new sign-ups are switched off in the demo"
	case strings.HasPrefix(path, "/guss/"):
		return "Guss isn't connected in the demo"
	}
	return ""
}

// DemoGuard refuses, in demo mode, the requests that could reach the
// outside world. A real Friday (no demo users) passes everything.
func DemoGuard(demo map[string]string, next http.Handler) http.Handler {
	if len(demo) == 0 {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if why := demoRefused(r.Method, r.URL.Path); why != "" {
			writeError(w, http.StatusForbidden, why)
			return
		}
		next.ServeHTTP(w, r)
	})
}
