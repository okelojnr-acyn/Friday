package auth

import (
	"encoding/json"
	"net/http"
)

// INVITABLE_ROLES deliberately excludes "owner" -- an org only ever gets
// an owner at signup time (completeSignup); promoting someone to owner
// afterward isn't a feature yet, and inviting one in directly would be
// a strange way to create one.
var invitableRoles = map[string]bool{"admin": true, "member": true, "viewer": true}

type inviteRequest struct {
	Email string `json:"email"`
	Role  string `json:"role"`
}

// InviteMember emails an invite code to join the caller's org -- reuses
// the exact same OtpStore machinery as Register (same 6-digit code, same
// cooldown/attempt limits), just with purpose "invite" and a payload
// carrying which org/role to join instead of which org to create. Gated
// to admin/owner, same inline role check every other admin-only kernel
// endpoint uses (see org.Catalog.SetInstalled, integrations.Handlers).
func (h *Handlers) InviteMember(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if !(claims.Role == "owner" || claims.Role == "admin") {
		writeError(w, http.StatusForbidden, "requires admin or owner")
		return
	}

	var req inviteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Email == "" {
		writeError(w, http.StatusBadRequest, "email is required")
		return
	}
	if !invitableRoles[req.Role] {
		writeError(w, http.StatusBadRequest, "role must be one of admin, member, viewer")
		return
	}

	ctx := r.Context()
	var exists bool
	if err := h.Pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM core.users WHERE email = $1)`, req.Email).Scan(&exists); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "an account with that email already exists -- multi-org membership for an existing account isn't supported yet")
		return
	}

	code, err := h.Otp.Request(ctx, req.Email, "invite", map[string]any{
		"org_id": claims.OrgID,
		"role":   req.Role,
	})
	if err != nil {
		writeError(w, http.StatusTooManyRequests, err.Error())
		return
	}
	_ = h.Mailer.Send(req.Email, "You've been invited to join a Friday organization",
		"Your invite code is "+code+". It expires in 10 minutes. "+
			"Go to the Friday login page, choose \"Join with an invite\", and enter this code to finish joining.")

	writeJSON(w, http.StatusAccepted, map[string]string{
		"message": "invite sent",
		"email":   req.Email,
	})
}

type acceptInviteRequest struct {
	Email    string `json:"email"`
	Code     string `json:"code"`
	FullName string `json:"full_name"`
}

// AcceptInvite is InviteMember's counterpart -- structurally identical to
// completeSignup, except it joins the org_id/role already carried in the
// invite's OTP payload instead of creating a brand new org, and skips
// the "seed every app" step (the org already has its own app_installs).
func (h *Handlers) AcceptInvite(w http.ResponseWriter, r *http.Request) {
	var req acceptInviteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()

	payload, err := h.Otp.Verify(ctx, req.Email, "invite", req.Code)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "invalid or expired code")
		return
	}
	orgID, _ := payload["org_id"].(string)
	role, _ := payload["role"].(string)
	if orgID == "" || role == "" {
		writeError(w, http.StatusInternalServerError, "invite payload is missing org_id or role")
		return
	}

	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer tx.Rollback(ctx)

	var userID string
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.users (email, full_name) VALUES ($1, $2) RETURNING id`,
		req.Email, req.FullName,
	).Scan(&userID); err != nil {
		writeError(w, http.StatusConflict, "a user with that email already exists")
		return
	}

	if _, err := tx.Exec(ctx,
		`INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, $3)`,
		orgID, userID, role,
	); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	token, err := h.Issuer.Issue(userID, orgID, role, req.Email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: role, Email: req.Email})
}
