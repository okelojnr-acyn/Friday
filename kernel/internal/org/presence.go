package org

import (
	"net/http"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
)

// Seen is one person's signs of being at work since a time: their first
// till sign-in (and which till), and their first and last moment on
// Friday or Minions. Presence only; hours belong to Tally.
type Seen struct {
	UserID     string     `json:"user_id"`
	TillAt     *time.Time `json:"till_at"`
	Till       string     `json:"till"`
	AppFirstAt *time.Time `json:"app_first_at"`
	LastAt     *time.Time `json:"last_at"`
}

// SeenSince (GET /internal/people/{org_id}/seen?since=RFC3339&user_id=...):
// who among user_id showed up since `since` (the business's midnight).
// Apps only (Minions' "who's in today").
func (p *People) SeenSince(w http.ResponseWriter, r *http.Request) {
	if !svcauth.Bearer(r, p.InternalToken) {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	since, err := time.Parse(time.RFC3339, r.URL.Query().Get("since"))
	if err != nil {
		peopleError(w, http.StatusBadRequest, "since is an RFC 3339 time")
		return
	}
	users := r.URL.Query()["user_id"]
	if len(users) > 500 {
		users = users[:500]
	}
	rows, err := p.Pool.Query(r.Context(), `
		WITH till AS (
			SELECT DISTINCT ON (e.user_id) e.user_id, e.created_at, COALESCE(d.name, '') AS till
			FROM core.pos_pin_events e LEFT JOIN core.pos_devices d ON d.id = e.device_id
			WHERE e.org_id::text = $1 AND e.kind IN ('signin', 'resumed', 'unlocked') AND e.created_at >= $2
			  AND e.user_id::text = ANY($3)
			ORDER BY e.user_id, e.created_at
		), app AS (
			-- first_at only when they signed in today (an older session's
			-- start says nothing about when they arrived).
			SELECT user_id, CASE WHEN min(created_at) >= $2 THEN min(created_at) END AS first_at, max(last_seen_at) AS last_at
			FROM core.sessions WHERE last_seen_at >= $2 AND user_id::text = ANY($3)
			GROUP BY user_id
		), last_till AS (
			SELECT user_id, max(created_at) AS at FROM core.pos_pin_events
			WHERE org_id::text = $1 AND created_at >= $2 AND user_id::text = ANY($3) GROUP BY user_id
		)
		SELECT u.id::text, till.created_at, COALESCE(till.till, ''), app.first_at, GREATEST(app.last_at, last_till.at)
		FROM core.users u
		LEFT JOIN till ON till.user_id = u.id
		LEFT JOIN app ON app.user_id = u.id
		LEFT JOIN last_till ON last_till.user_id = u.id
		WHERE u.id::text = ANY($3) AND (till.user_id IS NOT NULL OR app.user_id IS NOT NULL)`, r.PathValue("org_id"), since, users)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't load who's in")
		return
	}
	defer rows.Close()
	out := []Seen{}
	for rows.Next() {
		var s Seen
		if rows.Scan(&s.UserID, &s.TillAt, &s.Till, &s.AppFirstAt, &s.LastAt) == nil {
			out = append(out, s)
		}
	}
	peopleJSON(w, http.StatusOK, out)
}
