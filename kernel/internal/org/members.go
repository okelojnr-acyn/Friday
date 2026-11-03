package org

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Members is the org roster -- who's in this org and what role they
// have. Invites (adding a brand new person) live in internal/auth
// (InviteMember/AcceptInvite) since they reuse the OTP machinery; this
// is the plain CRUD-ish half for people already in core.memberships.
type Members struct {
	Pool *pgxpool.Pool
}

var settableRoles = map[string]bool{"owner": true, "admin": true, "member": true, "viewer": true}

type memberView struct {
	UserID    string    `json:"user_id"`
	Email     string    `json:"email"`
	FullName  string    `json:"full_name"`
	Role      string    `json:"role"`
	CreatedAt time.Time `json:"created_at"`
}

// List is readable by any authenticated member, not just admins --
// consistent with the "org-wide read" trust model every other resource
// in Friday already uses (see ARCHITECTURE.md); role-gating only
// applies to the mutating endpoints below.
func (m *Members) List(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	rows, err := m.Pool.Query(r.Context(), `
		SELECT u.id, u.email, u.full_name, mem.role, mem.created_at
		FROM core.memberships mem
		JOIN core.users u ON u.id = mem.user_id
		WHERE mem.org_id = $1
		ORDER BY mem.created_at
	`, claims.OrgID)
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	members := []memberView{}
	for rows.Next() {
		var mv memberView
		if err := rows.Scan(&mv.UserID, &mv.Email, &mv.FullName, &mv.Role, &mv.CreatedAt); err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		members = append(members, mv)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(members)
}

func requireAdmin(w http.ResponseWriter, r *http.Request) (*auth.Claims, bool) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return nil, false
	}
	if !(claims.Role == "owner" || claims.Role == "admin") {
		http.Error(w, "requires admin or owner", http.StatusForbidden)
		return nil, false
	}
	return claims, true
}

// ownerCount is shared by SetRole and Remove -- both need to refuse an
// action that would leave the org with zero owners.
func (m *Members) ownerCount(r *http.Request, orgID string) (int, error) {
	var count int
	err := m.Pool.QueryRow(r.Context(),
		`SELECT count(*) FROM core.memberships WHERE org_id = $1 AND role = 'owner'`, orgID,
	).Scan(&count)
	return count, err
}

type roleUpdateRequest struct {
	Role string `json:"role"`
}

// SetRole changes another member's role. Demoting the org's only owner
// is refused outright -- there's no "transfer ownership" ceremony yet,
// so losing the last owner would leave the org with nobody able to
// manage it at all.
func (m *Members) SetRole(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}
	targetUserID := r.PathValue("user_id")

	var req roleUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if !settableRoles[req.Role] {
		http.Error(w, "role must be one of owner, admin, member, viewer", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	var currentRole string
	if err := m.Pool.QueryRow(ctx,
		`SELECT role FROM core.memberships WHERE org_id = $1 AND user_id = $2`, claims.OrgID, targetUserID,
	).Scan(&currentRole); err != nil {
		http.Error(w, "member not found", http.StatusNotFound)
		return
	}

	if currentRole == "owner" && req.Role != "owner" {
		count, err := m.ownerCount(r, claims.OrgID)
		if err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		if count <= 1 {
			http.Error(w, "cannot demote the org's only owner", http.StatusBadRequest)
			return
		}
	}

	if _, err := m.Pool.Exec(ctx,
		`UPDATE core.memberships SET role = $1 WHERE org_id = $2 AND user_id = $3`,
		req.Role, claims.OrgID, targetUserID,
	); err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Remove deletes a membership -- not the core.users row itself (the
// person might belong to other memberships, or just lose access to
// this one org while keeping their account). Same last-owner guard as
// SetRole.
func (m *Members) Remove(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}
	targetUserID := r.PathValue("user_id")
	ctx := r.Context()

	var currentRole string
	if err := m.Pool.QueryRow(ctx,
		`SELECT role FROM core.memberships WHERE org_id = $1 AND user_id = $2`, claims.OrgID, targetUserID,
	).Scan(&currentRole); err != nil {
		http.Error(w, "member not found", http.StatusNotFound)
		return
	}

	if currentRole == "owner" {
		count, err := m.ownerCount(r, claims.OrgID)
		if err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		if count <= 1 {
			http.Error(w, "cannot remove the org's only owner", http.StatusBadRequest)
			return
		}
	}

	if _, err := m.Pool.Exec(ctx,
		`DELETE FROM core.memberships WHERE org_id = $1 AND user_id = $2`, claims.OrgID, targetUserID,
	); err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
