package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Invite links (plan section 12.6, step 3). An owner or admin invites
// anyone below owner; a branch manager invites team leaders and staff into
// their own locations, with job permissions short of hr and accounting.
// The link is valid 7 days and used once; joining applies the role,
// permissions, locations and reporting line decided here.

var invitePerms = []string{"cashier", "warehouse", "logistics", "purchasing", "sales", "accounting", "hr"}

// What a branch manager may hand out.
var managerInviteRoles = []string{"team_leader", "member"}
var managerInvitePerms = []string{"cashier", "warehouse", "logistics", "purchasing", "sales"}

type inviteLinkRequest struct {
	Email     string   `json:"email"`
	FullName  string   `json:"full_name"`
	Role      string   `json:"role"`
	Perms     []string `json:"perms"`
	Locations []string `json:"locations"`
	ReportsTo string   `json:"reports_to"`
}

type inviteView struct {
	ID        string    `json:"id"`
	Email     string    `json:"email"`
	FullName  string    `json:"full_name"`
	Role      string    `json:"role"`
	Perms     []string  `json:"perms"`
	Locations []string  `json:"locations"`
	ReportsTo *string   `json:"reports_to"`
	CreatedAt time.Time `json:"created_at"`
	ExpiresAt time.Time `json:"expires_at"`
	Status    string    `json:"status"` // pending | accepted | revoked | expired
	Link      string    `json:"link,omitempty"`
}

func inviteTokenHash(token string) string {
	sum := sha256.Sum256([]byte("invite:" + token))
	return hex.EncodeToString(sum[:])
}

func newInviteToken() (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func (h *Handlers) inviteLink(token string) string {
	return strings.TrimRight(h.WebURL, "/") + "/join?invite=" + token
}

// CreateInvite (POST /orgs/invites): makes the invite, emails the link,
// and returns it so it can also be shared by SMS or WhatsApp.
func (h *Handlers) CreateInvite(w http.ResponseWriter, r *http.Request) {
	c, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	manager := c.Role == "branch_manager"
	if c.Via != "" || !(c.Role == "owner" || c.Role == "admin" || manager) {
		writeError(w, http.StatusForbidden, "only owners, admins and branch managers invite people")
		return
	}
	var req inviteLinkRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	req.FullName = strings.TrimSpace(req.FullName)
	if !strings.Contains(req.Email, "@") || len(req.Email) > 200 || len(req.FullName) > 120 {
		writeError(w, http.StatusBadRequest, "an invite needs the person's email address")
		return
	}
	if !invitableRoles[req.Role] {
		writeError(w, http.StatusBadRequest, "role must be one of admin, branch_manager, team_leader, member, viewer")
		return
	}
	perms := []string{}
	for _, p := range req.Perms {
		if !slices.Contains(invitePerms, p) {
			writeError(w, http.StatusBadRequest, "permissions are some of "+strings.Join(invitePerms, ", "))
			return
		}
		if !slices.Contains(perms, p) {
			perms = append(perms, p)
		}
	}
	if manager {
		if !slices.Contains(managerInviteRoles, req.Role) {
			writeError(w, http.StatusForbidden, "a branch manager invites team leaders and staff; ask an admin for other roles")
			return
		}
		for _, p := range perms {
			if !slices.Contains(managerInvitePerms, p) {
				writeError(w, http.StatusForbidden, "only an owner or admin gives "+p)
				return
			}
		}
		if len(req.Locations) == 0 && !slices.Contains(c.Locs, "*") {
			writeError(w, http.StatusBadRequest, "choose which of your locations they work at")
			return
		}
		for _, l := range req.Locations {
			if !slices.Contains(c.Locs, "*") && !slices.Contains(c.Locs, l) {
				writeError(w, http.StatusForbidden, "you can only invite people into your own locations")
				return
			}
		}
	}

	ctx := r.Context()
	var exists bool
	if err := h.Pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM core.users WHERE lower(email) = $1)`, req.Email).Scan(&exists); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "an account with that email already exists -- multi-org membership for an existing account isn't supported yet")
		return
	}
	// Locations and the boss must be this business's.
	var okLocs int
	if err := h.Pool.QueryRow(ctx,
		`SELECT count(*) FROM core.locations WHERE org_id = $1 AND id::text = ANY($2)`, c.OrgID, req.Locations,
	).Scan(&okLocs); err != nil || okLocs != len(uniq(req.Locations)) {
		writeError(w, http.StatusBadRequest, "a location isn't one of this business's")
		return
	}
	var reportsTo *string
	if req.ReportsTo != "" {
		var found bool
		h.Pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM core.memberships WHERE org_id = $1 AND user_id::text = $2)`,
			c.OrgID, req.ReportsTo).Scan(&found)
		if !found {
			writeError(w, http.StatusBadRequest, "the person they report to isn't in this business")
			return
		}
		reportsTo = &req.ReportsTo
	} else if manager {
		// Someone a branch manager invites reports to them by default.
		reportsTo = &c.Subject
	}

	token, err := newInviteToken()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make the invite")
		return
	}
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make the invite")
		return
	}
	defer tx.Rollback(ctx)
	// A newer invite to the same person replaces an older pending one.
	tx.Exec(ctx, `UPDATE core.invites SET revoked_at = now()
		WHERE org_id = $1 AND lower(email) = $2 AND accepted_at IS NULL AND revoked_at IS NULL`, c.OrgID, req.Email)
	var v inviteView
	if err := tx.QueryRow(ctx, `
		INSERT INTO core.invites (org_id, email, full_name, role, perms, locations, reports_to, token_hash, invited_by)
		VALUES ($1, $2, $3, $4, $5, $6::uuid[], $7::uuid, $8, $9::uuid)
		RETURNING id::text, created_at, expires_at`,
		c.OrgID, req.Email, req.FullName, req.Role, perms, uniq(req.Locations), reportsTo, inviteTokenHash(token), c.Subject,
	).Scan(&v.ID, &v.CreatedAt, &v.ExpiresAt); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make the invite")
		return
	}
	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't make the invite")
		return
	}
	var orgName string
	h.Pool.QueryRow(ctx, `SELECT name FROM core.orgs WHERE id = $1`, c.OrgID).Scan(&orgName)
	link := h.inviteLink(token)
	if h.Mailer != nil {
		_ = h.Mailer.Send(req.Email, "You're invited to "+orgName+" on Friday",
			"Hello "+firstNonEmpty(req.FullName, "there")+",\n\n"+orgName+" has invited you to join them on Friday as "+
				roleWords(req.Role)+".\n\nOpen this link to join (it works once, for 7 days):\n"+link+"\n")
	}
	v.Email, v.FullName, v.Role, v.Perms, v.Locations, v.ReportsTo = req.Email, req.FullName, req.Role, perms, uniq(req.Locations), reportsTo
	v.Status, v.Link = "pending", link
	writeJSON(w, http.StatusCreated, v)
}

// ListInvites (GET /orgs/invites): owners and admins see every invite of
// the last 30 days; a branch manager sees the ones they sent.
func (h *Handlers) ListInvites(w http.ResponseWriter, r *http.Request) {
	c, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if !(c.Role == "owner" || c.Role == "admin" || c.Role == "branch_manager") {
		writeError(w, http.StatusForbidden, "only owners, admins and branch managers see invites")
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT id::text, email, full_name, role, perms, ARRAY(SELECT unnest(locations)::text), reports_to::text,
		       created_at, expires_at,
		       CASE WHEN accepted_at IS NOT NULL THEN 'accepted' WHEN revoked_at IS NOT NULL THEN 'revoked'
		            WHEN expires_at < now() THEN 'expired' ELSE 'pending' END
		FROM core.invites
		WHERE org_id = $1 AND created_at > now() - interval '30 days' AND ($2 OR invited_by::text = $3)
		ORDER BY created_at DESC LIMIT 200`, c.OrgID, c.Role != "branch_manager", c.Subject)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't load invites")
		return
	}
	defer rows.Close()
	out := []inviteView{}
	for rows.Next() {
		var v inviteView
		if err := rows.Scan(&v.ID, &v.Email, &v.FullName, &v.Role, &v.Perms, &v.Locations, &v.ReportsTo,
			&v.CreatedAt, &v.ExpiresAt, &v.Status); err != nil {
			writeError(w, http.StatusInternalServerError, "couldn't load invites")
			return
		}
		out = append(out, v)
	}
	writeJSON(w, http.StatusOK, out)
}

// RevokeInvite (DELETE /orgs/invites/{id}): owners and admins, or the
// branch manager who sent it. The link stops working at once.
func (h *Handlers) RevokeInvite(w http.ResponseWriter, r *http.Request) {
	c, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	tag, err := h.Pool.Exec(r.Context(), `
		UPDATE core.invites SET revoked_at = now()
		WHERE org_id = $1 AND id::text = $2 AND accepted_at IS NULL AND revoked_at IS NULL
		  AND ($3 OR (invited_by::text = $4 AND $5))`,
		c.OrgID, r.PathValue("id"), c.Role == "owner" || c.Role == "admin", c.Subject, c.Role == "branch_manager")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't revoke the invite")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusNotFound, "no open invite of yours by that id")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// PreviewInvite (GET /invites/{token}): public; what the join page shows
// before the person accepts.
func (h *Handlers) PreviewInvite(w http.ResponseWriter, r *http.Request) {
	var org, email, name, role string
	var expired, used bool
	err := h.Pool.QueryRow(r.Context(), `
		SELECT o.name, i.email, i.full_name, i.role, i.expires_at < now(), i.accepted_at IS NOT NULL OR i.revoked_at IS NOT NULL
		FROM core.invites i JOIN core.orgs o ON o.id = i.org_id WHERE i.token_hash = $1`,
		inviteTokenHash(r.PathValue("token"))).Scan(&org, &email, &name, &role, &expired, &used)
	if errors.Is(err, pgx.ErrNoRows) || used {
		writeError(w, http.StatusNotFound, "this invite link isn't valid any more; ask for a new one")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't read the invite")
		return
	}
	if expired {
		writeError(w, http.StatusGone, "this invite link has expired; ask for a new one")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"org_name": org, "email": email, "full_name": name, "role": role, "role_words": roleWords(role)})
}

// AcceptInviteLink (POST /invites/{token}/accept): public. Creates the
// account, joins the business with everything the invite decided, uses
// the invite up, and signs the person in.
func (h *Handlers) AcceptInviteLink(w http.ResponseWriter, r *http.Request) {
	var req struct {
		FullName string `json:"full_name"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't join")
		return
	}
	defer tx.Rollback(ctx)
	var orgID, email, name, role string
	var perms, locs []string
	var reportsTo *string
	// Claiming the invite and joining happen together: used once, even if
	// the link is opened twice at the same moment.
	err = tx.QueryRow(ctx, `
		UPDATE core.invites SET accepted_at = now()
		WHERE token_hash = $1 AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
		RETURNING org_id::text, email, full_name, role, perms, ARRAY(SELECT unnest(locations)::text), reports_to::text`,
		inviteTokenHash(r.PathValue("token"))).Scan(&orgID, &email, &name, &role, &perms, &locs, &reportsTo)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusGone, "this invite link isn't valid any more; ask for a new one")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't join")
		return
	}
	if n := strings.TrimSpace(req.FullName); n != "" && len(n) <= 120 {
		name = n
	}
	var userID string
	if err := tx.QueryRow(ctx, `INSERT INTO core.users (email, full_name) VALUES ($1, $2) RETURNING id::text`, email, name).Scan(&userID); err != nil {
		writeError(w, http.StatusConflict, "an account with that email already exists; sign in instead")
		return
	}
	// The boss may have left since the invite was sent.
	if reportsTo != nil {
		var still bool
		tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM core.memberships WHERE org_id = $1 AND user_id::text = $2)`, orgID, *reportsTo).Scan(&still)
		if !still {
			reportsTo = nil
		}
	}
	if _, err := tx.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role, perms, reports_to) VALUES ($1, $2::uuid, $3, $4, $5::uuid)`,
		orgID, userID, role, perms, reportsTo); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't join")
		return
	}
	for _, l := range locs {
		if _, err := tx.Exec(ctx, `
			INSERT INTO core.membership_locations (org_id, user_id, location_id)
			SELECT $1, $2::uuid, id FROM core.locations WHERE org_id = $1 AND id::text = $3 ON CONFLICT DO NOTHING`,
			orgID, userID, l); err != nil {
			writeError(w, http.StatusInternalServerError, "couldn't join")
			return
		}
	}
	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "couldn't join")
		return
	}
	token, err := h.Issuer.Issue(userID, orgID, role, email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: role, Email: email})
}

// pendingInviteFor is the newest open invite link for email, for the POS
// "email me a code" path (a cashier invited minutes before their shift).
func (h *Handlers) pendingInviteFor(ctx context.Context, email string) (orgID, role string, ok bool) {
	err := h.Pool.QueryRow(ctx, `
		SELECT org_id::text, role FROM core.invites
		WHERE lower(email) = $1 AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
		ORDER BY created_at DESC LIMIT 1`, strings.ToLower(strings.TrimSpace(email))).Scan(&orgID, &role)
	return orgID, role, err == nil
}

func uniq(xs []string) []string {
	out := []string{}
	for _, x := range xs {
		if x != "" && !slices.Contains(out, x) {
			out = append(out, x)
		}
	}
	return out
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func roleWords(role string) string {
	switch role {
	case "admin":
		return "an admin"
	case "branch_manager":
		return "a branch manager"
	case "team_leader":
		return "a team leader"
	case "viewer":
		return "a viewer (read only)"
	default:
		return "staff"
	}
}
