package org

import (
	"encoding/json"
	"net/http"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
)

// ApprovalLimits: the most each role may approve on one request, in the
// business's cents (core.orgs.approval_limits). Owners and admins have none.
type ApprovalLimits struct {
	TeamLeader    int64 `json:"team_leader"`
	BranchManager int64 `json:"branch_manager"`
}

// DefaultApprovalLimits: KES 2,000 and 20,000 (plan 12.9).
func DefaultApprovalLimits() ApprovalLimits {
	return ApprovalLimits{TeamLeader: 200_000, BranchManager: 2_000_000}
}

func (l ApprovalLimits) valid() bool {
	const most = 1_000_000_000_00 // a billion, in cents
	return l.TeamLeader >= 0 && l.BranchManager >= 0 && l.TeamLeader <= most && l.BranchManager <= most
}

func (p *People) limits(r *http.Request, orgID string) (ApprovalLimits, error) {
	var raw []byte
	l := DefaultApprovalLimits()
	if err := p.Pool.QueryRow(r.Context(), `SELECT approval_limits FROM core.orgs WHERE id::text = $1`, orgID).Scan(&raw); err != nil {
		return l, err
	}
	json.Unmarshal(raw, &l) // stored fields win; missing ones keep the default
	return l, nil
}

// GetApprovalLimits (GET /orgs/approval-limits): any member.
func (p *People) GetApprovalLimits(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	l, err := p.limits(r, c.OrgID)
	if err != nil {
		peopleError(w, http.StatusNotFound, "organisation not found")
		return
	}
	peopleJSON(w, http.StatusOK, l)
}

// PutApprovalLimits (PUT /orgs/approval-limits): owners and admins.
func (p *People) PutApprovalLimits(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if c.Via != "" || (c.Role != "owner" && c.Role != "admin") {
		peopleError(w, http.StatusForbidden, "only owners and admins set approval limits")
		return
	}
	var l ApprovalLimits
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&l); err != nil || !l.valid() {
		peopleError(w, http.StatusBadRequest, "limits are amounts from 0 up to a billion")
		return
	}
	raw, _ := json.Marshal(l)
	if _, err := p.Pool.Exec(r.Context(), `UPDATE core.orgs SET approval_limits = $2 WHERE id::text = $1`, c.OrgID, raw); err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't save the limits")
		return
	}
	peopleJSON(w, http.StatusOK, l)
}

// Approver is one person a request can go to.
type Approver struct {
	UserID string `json:"user_id"`
	Role   string `json:"role"`
	Name   string `json:"name"`
	Email  string `json:"email"`
}

// Approvers (GET /internal/people/{org_id}/approvers/{user_id}): who a
// request from user_id goes to. chain: who they report to, then who that
// person reports to, and so on (nearest first). top: the owners and
// admins, who decide anything nobody in the chain may. Apps only.
func (p *People) Approvers(w http.ResponseWriter, r *http.Request) {
	if !svcauth.Bearer(r, p.InternalToken) {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	orgID, userID := r.PathValue("org_id"), r.PathValue("user_id")
	l, err := p.limits(r, orgID)
	if err != nil {
		peopleError(w, http.StatusNotFound, "organisation not found")
		return
	}
	scan := func(sql string, args ...any) ([]Approver, error) {
		rows, err := p.Pool.Query(r.Context(), sql, args...)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := []Approver{}
		for rows.Next() {
			var a Approver
			if err := rows.Scan(&a.UserID, &a.Role, &a.Name, &a.Email); err != nil {
				return nil, err
			}
			out = append(out, a)
		}
		return out, rows.Err()
	}
	chain, err := scan(`
		WITH RECURSIVE up(user_id, depth) AS (
			SELECT reports_to, 1 FROM core.memberships WHERE org_id::text = $1 AND user_id::text = $2 AND reports_to IS NOT NULL
			UNION
			SELECT m.reports_to, up.depth + 1 FROM core.memberships m JOIN up ON m.user_id = up.user_id
			WHERE m.org_id::text = $1 AND m.reports_to IS NOT NULL AND up.depth < 20
		)
		SELECT m.user_id::text, m.role, u.full_name, u.email FROM up
		JOIN core.memberships m ON m.user_id = up.user_id AND m.org_id::text = $1
		JOIN core.users u ON u.id = m.user_id
		WHERE m.user_id::text <> $2
		ORDER BY up.depth`, orgID, userID)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't load approvers")
		return
	}
	top, err := scan(`
		SELECT m.user_id::text, m.role, u.full_name, u.email FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE m.org_id::text = $1 AND m.role IN ('owner', 'admin') AND m.user_id::text <> $2
		ORDER BY m.role DESC, m.created_at`, orgID, userID)
	if err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't load approvers")
		return
	}
	peopleJSON(w, http.StatusOK, map[string]any{"limits": l, "chain": chain, "top": top})
}

// Person (GET /internal/people/{org_id}/person?user_id=...|email=...): one
// member of the business (id, role, name, email), 404 when they aren't
// one. Apps use it to check whom something is given to. Apps only.
func (p *People) Person(w http.ResponseWriter, r *http.Request) {
	if !svcauth.Bearer(r, p.InternalToken) {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	q := r.URL.Query()
	var a Approver
	err := p.Pool.QueryRow(r.Context(), `
		SELECT m.user_id::text, m.role, u.full_name, u.email FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE m.org_id::text = $1 AND (($2 <> '' AND m.user_id::text = $2) OR ($2 = '' AND $3 <> '' AND lower(u.email) = lower($3)))`,
		r.PathValue("org_id"), q.Get("user_id"), q.Get("email")).Scan(&a.UserID, &a.Role, &a.Name, &a.Email)
	if err != nil {
		peopleError(w, http.StatusNotFound, "not a member of this business")
		return
	}
	peopleJSON(w, http.StatusOK, a)
}
