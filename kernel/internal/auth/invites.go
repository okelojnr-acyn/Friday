package auth

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
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

	userID, err := h.joinOrg(ctx, req.Email, req.FullName, orgID, role)
	if err != nil {
		writeError(w, http.StatusConflict, err.Error())
		return
	}

	token, err := h.Issuer.Issue(userID, orgID, role, req.Email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: role, Email: req.Email})
}

// joinOrg creates the user + membership row an accepted invite needs --
// shared by AcceptInvite and PosVerifyCode below, since both end with
// "this email, which an admin already decided should join orgID at
// role, now has a real account."
func (h *Handlers) joinOrg(ctx context.Context, email, fullName, orgID, role string) (userID string, err error) {
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)

	if err := tx.QueryRow(ctx,
		`INSERT INTO core.users (email, full_name) VALUES ($1, $2) RETURNING id`,
		email, fullName,
	).Scan(&userID); err != nil {
		return "", errors.New("a user with that email already exists")
	}

	if _, err := tx.Exec(ctx,
		`INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, $3)`,
		orgID, userID, role,
	); err != nil {
		return "", err
	}

	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	return userID, nil
}

// findPendingInvitePayload returns the org_id/role from the most
// recent invite ever sent to email, regardless of whether that
// invite's own code was consumed or has since expired -- PosRequestCode
// only needs the org/role an admin already decided on, not that exact
// code; it mints a fresh one. An email that already joined is never
// reached through here (PosRequestCode/PosVerifyCode both check
// findUserByEmail first), so there's no risk of resurrecting a stale
// invite for someone who already has an account.
func (h *Handlers) findPendingInvitePayload(ctx context.Context, email string) (orgID, role string, ok bool) {
	var payloadRaw []byte
	err := h.Pool.QueryRow(ctx, `
		SELECT payload FROM core.otp_codes WHERE email = $1 AND purpose = 'invite'
		ORDER BY created_at DESC LIMIT 1
	`, strings.ToLower(strings.TrimSpace(email))).Scan(&payloadRaw)
	if err != nil {
		return "", "", false
	}
	var payload map[string]any
	if err := json.Unmarshal(payloadRaw, &payload); err != nil {
		return "", "", false
	}
	orgID, _ = payload["org_id"].(string)
	role, _ = payload["role"].(string)
	return orgID, role, orgID != "" && role != ""
}

type posCodeRequest struct {
	Email string `json:"email"`
}

// PosRequestCode is the POS clock-in device's "email me a code" entry
// point -- deliberately not a reuse of OtpRequest, which stays silent
// about whether an email has an account (right for a public login
// page, wrong here: the honest answer -- "ask your admin to invite you
// first" -- is exactly what whoever's standing at the register needs
// to hear instead of a code that was never sent). Covers two cases:
// an existing account (send a login code, same as OtpRequest), or an
// email an admin already invited, even if that invite's own emailed
// code has long since expired -- a real gap otherwise, since a cashier
// invited minutes before their shift may not open that email until
// they're already standing at the register.
func (h *Handlers) PosRequestCode(w http.ResponseWriter, r *http.Request) {
	var req posCodeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()

	if _, _, ok := findUserByEmail(ctx, h.Pool, req.Email); ok {
		code, err := h.Otp.Request(ctx, req.Email, "login", nil)
		if err != nil {
			writeError(w, http.StatusTooManyRequests, err.Error())
			return
		}
		_ = h.Mailer.Send(req.Email, "Your Friday login code",
			"Your login code is "+code+". It expires in 10 minutes.")
		writeJSON(w, http.StatusAccepted, map[string]string{"message": "code sent"})
		return
	}

	if orgID, role, ok := h.findPendingInvitePayload(ctx, req.Email); ok {
		code, err := h.Otp.Request(ctx, req.Email, "invite", map[string]any{"org_id": orgID, "role": role})
		if err != nil {
			writeError(w, http.StatusTooManyRequests, err.Error())
			return
		}
		_ = h.Mailer.Send(req.Email, "Your Friday clock-in code",
			"Your code is "+code+". It expires in 10 minutes.")
		writeJSON(w, http.StatusAccepted, map[string]string{"message": "code sent"})
		return
	}

	writeError(w, http.StatusNotFound, "this email hasn't been added to your team yet -- ask an admin to invite you first")
}

type posVerifyRequest struct {
	Email    string `json:"email"`
	Code     string `json:"code"`
	FullName string `json:"full_name"`
}

// PosVerifyCode completes PosRequestCode -- same login-or-join duality
// as OtpVerify, but the join branch is always AcceptInvite's (joinOrg),
// never completeSignup's. Deliberately: a shared register device is
// exactly the wrong place to let anyone type an arbitrary email and
// spin up a brand new business -- this can only ever attach someone to
// an org an admin already chose to invite them into.
func (h *Handlers) PosVerifyCode(w http.ResponseWriter, r *http.Request) {
	var req posVerifyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()

	if userID, _, ok := findUserByEmail(ctx, h.Pool, req.Email); ok {
		if _, err := h.Otp.Verify(ctx, req.Email, "login", req.Code); err != nil {
			writeError(w, http.StatusUnauthorized, "invalid or expired code")
			return
		}
		h.issueSessionForUser(w, ctx, userID, req.Email)
		return
	}

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

	userID, err := h.joinOrg(ctx, req.Email, req.FullName, orgID, role)
	if err != nil {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	token, err := h.Issuer.Issue(userID, orgID, role, req.Email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: role, Email: req.Email})
}
