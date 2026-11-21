package org

import (
	"encoding/json"
	"errors"
	"net/http"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/access"
	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// People is the access side of a membership (plan section 12): role,
// permissions, locations, who someone reports to, the staff ID, and the
// business's locations.
type People struct {
	Pool *pgxpool.Pool
	// InternalToken guards the apps-only routes (KERNEL_EVENTS_TOKEN).
	InternalToken string
}

// AtLocations (GET /internal/people/{org_id}?location=...): the user ids
// of everyone at any of those locations, plus everyone with no locations
// listed (they work at all of them). Apps use it for a branch manager's
// "loc" scope over people (staff lists, claims). Apps only.
func (p *People) AtLocations(w http.ResponseWriter, r *http.Request) {
	if p.InternalToken == "" || r.Header.Get("Authorization") != "Bearer "+p.InternalToken {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	locs := r.URL.Query()["location"]
	rows, err := p.Pool.Query(r.Context(), `
		SELECT m.user_id::text FROM core.memberships m
		WHERE m.org_id::text = $1 AND (
			NOT EXISTS (SELECT 1 FROM core.membership_locations ml WHERE ml.org_id = m.org_id AND ml.user_id = m.user_id)
			OR EXISTS (SELECT 1 FROM core.membership_locations ml WHERE ml.org_id = m.org_id AND ml.user_id = m.user_id
			           AND ml.location_id::text = ANY($2)))
		ORDER BY 1`, r.PathValue("org_id"), locs)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't load people")
		return
	}
	defer rows.Close()
	ids := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't load people")
			return
		}
		ids = append(ids, id)
	}
	peopleJSON(w, http.StatusOK, map[string]any{"user_ids": ids})
}

func peopleJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func peopleError(w http.ResponseWriter, status int, msg string) {
	peopleJSON(w, status, map[string]string{"error": msg})
}

// MyPermissions (GET /orgs/me/permissions): what the signed-in person may
// do, rule by rule, so the web shows only what they can use. Read from the
// token, which the kernel filled from the same rules the apps enforce.
func (p *People) MyPermissions(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	var staffID *string
	p.Pool.QueryRow(r.Context(),
		`SELECT staff_id FROM core.memberships WHERE org_id = $1 AND user_id::text = $2`, c.OrgID, c.Subject,
	).Scan(&staffID)
	peopleJSON(w, http.StatusOK, map[string]any{
		"role":      c.Role,
		"perms":     orEmpty(c.Perms),
		"locations": orEmpty(c.Locs),
		"team_size": len(c.Team),
		"staff_id":  staffID,
		"rules":     access.All(c.Role, c.Perms),
	})
}

// AccessRules (GET /orgs/access/rules): the whole who-sees-what table,
// for the People page's "what can this role do?" panel.
func (p *People) AccessRules(w http.ResponseWriter, r *http.Request) {
	if _, ok := auth.FromContext(r.Context()); !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	peopleJSON(w, http.StatusOK, map[string]any{"roles": access.Roles, "perms": access.Perms, "rules": access.Rules})
}

func orEmpty(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

type locationView struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Kind    string `json:"kind"`
	Address string `json:"address"`
}

// Locations (GET /orgs/locations): the business's stores, warehouses and
// offices. Any member may list them (names only).
func (p *People) Locations(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	rows, err := p.Pool.Query(r.Context(),
		`SELECT id::text, name, kind, address FROM core.locations WHERE org_id = $1 ORDER BY created_at, name`, c.OrgID)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't load the locations")
		return
	}
	defer rows.Close()
	out := []locationView{}
	for rows.Next() {
		var l locationView
		if err := rows.Scan(&l.ID, &l.Name, &l.Kind, &l.Address); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't load the locations")
			return
		}
		out = append(out, l)
	}
	peopleJSON(w, http.StatusOK, out)
}

var locationKinds = []string{"store", "warehouse", "office", "other"}

// SaveLocation (POST /orgs/locations, PATCH /orgs/locations/{id}): owners
// and admins add or rename a location.
func (p *People) SaveLocation(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if c.Via != "" || access.Scope("settings.write", c.Role, c.Perms) == "" {
		peopleError(w, http.StatusForbidden, "only owners and admins change locations")
		return
	}
	var req locationView
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil {
		peopleError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	req.Address = strings.TrimSpace(req.Address)
	if req.Kind == "" {
		req.Kind = "store"
	}
	if req.Name == "" || len(req.Name) > 80 || len(req.Address) > 200 || !slices.Contains(locationKinds, req.Kind) {
		peopleError(w, http.StatusBadRequest, "a location needs a name (up to 80 characters) and a kind: store, warehouse, office or other")
		return
	}
	var id string
	var err error
	if r.PathValue("id") == "" {
		err = p.Pool.QueryRow(r.Context(),
			`INSERT INTO core.locations (org_id, name, kind, address) VALUES ($1, $2, $3, $4) RETURNING id::text`,
			c.OrgID, req.Name, req.Kind, req.Address).Scan(&id)
	} else {
		err = p.Pool.QueryRow(r.Context(),
			`UPDATE core.locations SET name = $3, kind = $4, address = $5 WHERE org_id = $1 AND id::text = $2 RETURNING id::text`,
			c.OrgID, r.PathValue("id"), req.Name, req.Kind, req.Address).Scan(&id)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		peopleError(w, http.StatusNotFound, "no such location")
		return
	}
	if err != nil {
		peopleError(w, http.StatusConflict, "there's already a location called "+req.Name)
		return
	}
	req.ID = id
	peopleJSON(w, http.StatusOK, req)
}

type personUpdate struct {
	Role      *string   `json:"role"`
	Perms     *[]string `json:"perms"`
	Locations *[]string `json:"locations"`
	// "" clears it.
	ReportsTo *string `json:"reports_to"`
}

// UpdatePerson (PATCH /orgs/members/{user_id}): role, permissions,
// locations and who they report to, in one save. Owners change anyone;
// admins change anyone but owners and never make owners. (Branch
// managers inviting into their own locations is step 3.)
func (p *People) UpdatePerson(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if c.Via != "" || (c.Role != "owner" && c.Role != "admin") {
		peopleError(w, http.StatusForbidden, "only owners and admins change people's access")
		return
	}
	target := r.PathValue("user_id")
	var req personUpdate
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&req); err != nil {
		peopleError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't save")
		return
	}
	defer tx.Rollback(ctx)

	var current string
	if err := tx.QueryRow(ctx,
		`SELECT role FROM core.memberships WHERE org_id = $1 AND user_id::text = $2 FOR UPDATE`, c.OrgID, target,
	).Scan(&current); err != nil {
		peopleError(w, http.StatusNotFound, "no such person in this business")
		return
	}
	if c.Role == "admin" && current == "owner" {
		peopleError(w, http.StatusForbidden, "only an owner changes another owner")
		return
	}

	if req.Role != nil {
		role := *req.Role
		if !access.ValidRole(role) {
			peopleError(w, http.StatusBadRequest, "role must be one of "+strings.Join(access.Roles, ", "))
			return
		}
		if role == "owner" && c.Role != "owner" {
			peopleError(w, http.StatusForbidden, "only an owner makes someone an owner")
			return
		}
		if current == "owner" && role != "owner" {
			var owners int
			tx.QueryRow(ctx, `SELECT count(*) FROM core.memberships WHERE org_id = $1 AND role = 'owner'`, c.OrgID).Scan(&owners)
			if owners <= 1 {
				peopleError(w, http.StatusBadRequest, "the business needs at least one owner")
				return
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE core.memberships SET role = $3 WHERE org_id = $1 AND user_id::text = $2`,
			c.OrgID, target, role); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't save the role")
			return
		}
	}
	if req.Perms != nil {
		perms := []string{}
		for _, pm := range *req.Perms {
			if !access.ValidPerm(pm) {
				peopleError(w, http.StatusBadRequest, "permissions are some of "+strings.Join(access.Perms, ", "))
				return
			}
			if !slices.Contains(perms, pm) {
				perms = append(perms, pm)
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE core.memberships SET perms = $3 WHERE org_id = $1 AND user_id::text = $2`,
			c.OrgID, target, perms); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't save the permissions")
			return
		}
	}
	if req.Locations != nil {
		if _, err := tx.Exec(ctx, `DELETE FROM core.membership_locations WHERE org_id = $1 AND user_id::text = $2`,
			c.OrgID, target); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't save the locations")
			return
		}
		for _, loc := range *req.Locations {
			tag, err := tx.Exec(ctx, `
				INSERT INTO core.membership_locations (org_id, user_id, location_id)
				SELECT $1, $2::uuid, id FROM core.locations WHERE org_id = $1 AND id::text = $3
				ON CONFLICT DO NOTHING`, c.OrgID, target, loc)
			if err != nil || tag.RowsAffected() == 0 {
				peopleError(w, http.StatusBadRequest, "a location isn't one of this business's")
				return
			}
		}
	}
	if req.ReportsTo != nil {
		boss := strings.TrimSpace(*req.ReportsTo)
		if boss == "" {
			_, err = tx.Exec(ctx, `UPDATE core.memberships SET reports_to = NULL WHERE org_id = $1 AND user_id::text = $2`, c.OrgID, target)
		} else {
			if boss == target {
				peopleError(w, http.StatusBadRequest, "nobody reports to themselves")
				return
			}
			// The boss must be here, and mustn't (eventually) report to them.
			var loop bool
			err = tx.QueryRow(ctx, `
				WITH RECURSIVE up(user_id, reports_to, depth) AS (
					SELECT user_id, reports_to, 1 FROM core.memberships WHERE org_id = $1 AND user_id::text = $2
					UNION
					SELECT m.user_id, m.reports_to, up.depth + 1 FROM core.memberships m JOIN up ON m.user_id = up.reports_to
					WHERE m.org_id = $1 AND up.depth < 20
				)
				SELECT EXISTS (SELECT 1 FROM up WHERE user_id::text = $3)`, c.OrgID, boss, target).Scan(&loop)
			if err == nil && loop {
				peopleError(w, http.StatusBadRequest, "that would make a loop: they already report (through others) to this person")
				return
			}
			var tag interface{ RowsAffected() int64 }
			tag, err = tx.Exec(ctx, `
				UPDATE core.memberships SET reports_to = $3::uuid WHERE org_id = $1 AND user_id::text = $2
				AND EXISTS (SELECT 1 FROM core.memberships WHERE org_id = $1 AND user_id = $3::uuid)`, c.OrgID, target, boss)
			if err == nil && tag.RowsAffected() == 0 {
				peopleError(w, http.StatusBadRequest, "the person they report to isn't in this business")
				return
			}
		}
		if err != nil {
			peopleError(w, http.StatusBadRequest, "the person they report to isn't in this business")
			return
		}
	}
	if err := tx.Commit(ctx); err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't save")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
