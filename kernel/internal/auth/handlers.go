package auth

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/go-webauthn/webauthn/protocol"
	"github.com/go-webauthn/webauthn/webauthn"

	"github.com/acyn-innovation/friday/kernel/internal/mail"
)

// Handlers is every auth HTTP endpoint the kernel serves. Passwordless
// throughout -- a passkey (WebAuthn) ceremony or an emailed one-time
// code, no password field anywhere, matching Acyn Wallet's auth model
// (see README.md's "Passwordless everywhere" there).
type Handlers struct {
	Pool     *pgxpool.Pool
	Issuer   *Issuer
	WebAuthn *webauthn.WebAuthn
	Mailer   *mail.Mailer
	Otp      *OtpStore
}

type registerRequest struct {
	OrgName  string `json:"org_name"`
	Email    string `json:"email"`
	FullName string `json:"full_name"`
}

type authResponse struct {
	Token string `json:"token"`
	OrgID string `json:"org_id"`
	Role  string `json:"role"`
	Email string `json:"email"`
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

func slugify(name string) string {
	s := slugRe.ReplaceAllString(strings.ToLower(strings.TrimSpace(name)), "-")
	return strings.Trim(s, "-")
}

// Register starts a signup: no account exists yet after this call --
// it stores the pending org_name/email/full_name and emails a one-time
// code (purpose "signup"). The account itself is only created once that
// code is verified (OtpVerify below), so an email nobody owns can never
// end up with a live org attached to it.
func (h *Handlers) Register(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.OrgName == "" || req.Email == "" {
		writeError(w, http.StatusBadRequest, "org_name and email are required")
		return
	}

	ctx := r.Context()
	var exists bool
	if err := h.Pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM core.users WHERE email = $1)`, req.Email).Scan(&exists); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "an account with that email already exists -- log in instead")
		return
	}

	code, err := h.Otp.Request(ctx, req.Email, "signup", map[string]any{
		"org_name":  req.OrgName,
		"full_name": req.FullName,
	})
	if err != nil {
		writeError(w, http.StatusTooManyRequests, err.Error())
		return
	}
	_ = h.Mailer.Send(req.Email, "Your Friday verification code",
		"Your verification code is "+code+". It expires in 10 minutes.")

	writeJSON(w, http.StatusAccepted, map[string]string{
		"message": "check your email for a verification code",
		"email":   req.Email,
	})
}

type otpRequestBody struct {
	Email string `json:"email"`
}

// OtpRequest is the fallback login path's entry point: "email me a
// code." Deliberately the same response whether or not the email has an
// account -- only actually sends one when it does, so this endpoint
// can't be used to probe which emails are registered.
func (h *Handlers) OtpRequest(w http.ResponseWriter, r *http.Request) {
	var req otpRequestBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()
	if _, _, ok := findUserByEmail(ctx, h.Pool, req.Email); ok {
		if code, err := h.Otp.Request(ctx, req.Email, "login", nil); err == nil {
			_ = h.Mailer.Send(req.Email, "Your Friday login code",
				"Your login code is "+code+". It expires in 10 minutes.")
		}
	}
	writeJSON(w, http.StatusAccepted, map[string]string{
		"message": "if that email has an account, a code was sent",
	})
}

type otpVerifyBody struct {
	Email string `json:"email"`
	Code  string `json:"code"`
}

// OtpVerify completes either flow -- a brand new signup, or a fallback
// login for an existing account -- without the client needing to track
// which one it's in. Tries "login" first (the common case), then
// "signup" (which, on success, creates the account from the pending
// payload Register stored).
func (h *Handlers) OtpVerify(w http.ResponseWriter, r *http.Request) {
	var req otpVerifyBody
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	ctx := r.Context()

	if userID, _, ok := findUserByEmail(ctx, h.Pool, req.Email); ok {
		if _, err := h.Otp.Verify(ctx, req.Email, "login", req.Code); err == nil {
			h.issueSessionForUser(w, r.Context(), userID, req.Email)
			return
		}
	}

	payload, err := h.Otp.Verify(ctx, req.Email, "signup", req.Code)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "invalid or expired code")
		return
	}
	orgName, _ := payload["org_name"].(string)
	fullName, _ := payload["full_name"].(string)
	h.completeSignup(w, r, req.Email, orgName, fullName)
}

// completeSignup creates the org + user + owner membership + default
// app installs -- the same transaction the old password-based Register
// used to run inline, now the second half of the signup-OTP flow.
func (h *Handlers) completeSignup(w http.ResponseWriter, r *http.Request, email, orgName, fullName string) {
	ctx := r.Context()
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer tx.Rollback(ctx)

	var orgID string
	slug := slugify(orgName)
	if slug == "" {
		slug = slugify(email)
	}
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.orgs (name, slug) VALUES ($1, $2) RETURNING id`,
		orgName, slug,
	).Scan(&orgID); err != nil {
		writeError(w, http.StatusConflict, "an org with that name already exists")
		return
	}

	var userID string
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.users (email, full_name) VALUES ($1, $2) RETURNING id`,
		email, fullName,
	).Scan(&userID); err != nil {
		writeError(w, http.StatusConflict, "a user with that email already exists")
		return
	}

	if _, err := tx.Exec(ctx,
		`INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'owner')`,
		orgID, userID,
	); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	// New orgs get every app in the catalog enabled by default -- nobody
	// should land on an empty launcher after signing up.
	if _, err := tx.Exec(ctx,
		`INSERT INTO core.app_installs (org_id, app_name) SELECT $1, name FROM core.apps`,
		orgID,
	); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	if err := tx.Commit(ctx); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	token, err := h.Issuer.Issue(userID, orgID, "owner", email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: "owner", Email: email})
}

// issueSessionForUser is the shared "I know who this is, log them in"
// tail end of both the OTP-login and passkey-login paths: look up their
// org/role and mint a JWT.
func (h *Handlers) issueSessionForUser(w http.ResponseWriter, ctx context.Context, userID, email string) {
	var orgID, role string
	if err := h.Pool.QueryRow(ctx,
		`SELECT org_id, role FROM core.memberships WHERE user_id = $1 ORDER BY created_at LIMIT 1`,
		userID,
	).Scan(&orgID, &role); err != nil {
		writeError(w, http.StatusForbidden, "user has no org membership")
		return
	}
	token, err := h.Issuer.Issue(userID, orgID, role, email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusOK, authResponse{Token: token, OrgID: orgID, Role: role, Email: email})
}

// PasskeyLoginOptions starts a *discoverable* (usernameless) login
// ceremony -- no email needed at all. This is the correct shape for
// "unknown credentials" too: go-webauthn's BeginLogin requires a user
// with at least one existing credential (it errors "Found no
// credentials for user" otherwise, which is what a plain email-keyed
// design hits for every brand-new account), so login instead asks for
// *any* resident passkey the browser has for this origin and resolves
// *which* account it belongs to afterward, in PasskeyLoginVerify, via
// the credential's own embedded user handle. Requires passkeys to be
// registered as resident/discoverable credentials -- see
// PasskeyRegisterOptions' WithResidentKeyRequirement, matching Acyn
// Wallet's own `residentKey: 'preferred'` registration setting.
func (h *Handlers) PasskeyLoginOptions(w http.ResponseWriter, r *http.Request) {
	assertion, session, err := h.WebAuthn.BeginDiscoverableLogin()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not start passkey login: "+err.Error())
		return
	}
	sessionID, err := storeWebauthnChallenge(r.Context(), h.Pool, "login", session)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "publicKey": assertion.Response})
}

// PasskeyLoginVerify finishes the discoverable login ceremony. The
// browser's chosen credential carries a `userHandle` -- the same bytes
// this account's WebAuthnID was set to at registration time (its real
// database id) -- which is how `resolveUser` below identifies the
// account without the client ever stating one. `session_id` is a query
// param (the request body is the raw WebAuthn assertion response JSON,
// which go-webauthn's FinishPasskeyLogin parses from r.Body itself).
func (h *Handlers) PasskeyLoginVerify(w http.ResponseWriter, r *http.Request) {
	sessionID := r.URL.Query().Get("session_id")
	if sessionID == "" {
		writeError(w, http.StatusBadRequest, "session_id query param is required")
		return
	}
	ctx := r.Context()

	session, err := consumeWebauthnChallenge(ctx, h.Pool, sessionID, "login")
	if err != nil {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}

	resolveUser := func(rawID, userHandle []byte) (webauthn.User, error) {
		userID := string(userHandle)
		var email, fullName string
		if err := h.Pool.QueryRow(ctx,
			`SELECT email, full_name FROM core.users WHERE id = $1::uuid`, userID,
		).Scan(&email, &fullName); err != nil {
			return nil, errors.New("unknown credential")
		}
		return loadWebauthnUser(ctx, h.Pool, userID, email, fullName)
	}

	user, cred, err := h.WebAuthn.FinishPasskeyLogin(resolveUser, *session, r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "passkey authentication could not be verified")
		return
	}
	wu, ok := user.(*webauthnUser)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected user type")
		return
	}
	if err := updateWebauthnSignCount(ctx, h.Pool, cred.ID, cred.Authenticator.SignCount); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	h.issueSessionForUser(w, ctx, wu.id, wu.email)
}

// PasskeyRegisterOptions starts a ceremony to add a passkey to the
// *calling* account -- gated by RequireAuth, keyed off the caller's own
// JWT claims rather than a client-supplied email, so this can only ever
// add a credential to your own account, never anyone else's.
// WithResidentKeyRequirement is what makes the resulting passkey
// discoverable -- required for PasskeyLoginOptions' usernameless flow
// to be able to find it at all.
//
// `?purpose=pos` additionally constrains AuthenticatorAttachment to
// "platform" -- a real fingerprint/Face ID, not a roaming security key
// -- for the POS clock-in registration flow specifically
// (web/src/apps/pos/PosClockIn.tsx). This is a registration-time hint
// only: WebAuthn has no way to cryptographically enforce "platform-only"
// on a later assertion, so it's the practical mechanism, not a hard
// guarantee. The general "add a passkey to my account" flow (no
// purpose param) stays unconstrained -- an admin signing in from their
// laptop may legitimately want a security key.
func (h *Handlers) PasskeyRegisterOptions(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	ctx := r.Context()
	user, err := loadWebauthnUser(ctx, h.Pool, claims.Subject, claims.Email, "")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	// Required, not Preferred, in both branches below -- login
	// (PasskeyLoginOptions/Verify, this doc comment's own "required
	// for... to be able to find it at all") is always the discoverable/
	// usernameless ceremony, which can only ever see a resident
	// credential. Preferred let the authenticator/OS create a
	// non-resident one anyway, which registered fine but could then
	// never actually be found during login -- including via POS's own
	// "Scan to clock in," the exact bug PosClockIn.tsx's "New cashier?
	// Set up your fingerprint" flow was supposed to prevent a second
	// trip to the register for.
	registrationOpt := webauthn.WithResidentKeyRequirement(protocol.ResidentKeyRequirementRequired)
	if r.URL.Query().Get("purpose") == "pos" {
		registrationOpt = webauthn.WithAuthenticatorSelection(protocol.AuthenticatorSelection{
			AuthenticatorAttachment: protocol.Platform,
			ResidentKey:             protocol.ResidentKeyRequirementRequired,
			RequireResidentKey:      protocol.ResidentKeyRequired(),
			UserVerification:        protocol.VerificationRequired,
		})
	}
	creation, session, err := h.WebAuthn.BeginRegistration(user, registrationOpt)
	if err != nil {
		writeError(w, http.StatusBadRequest, "could not start passkey registration: "+err.Error())
		return
	}
	sessionID, err := storeWebauthnChallenge(ctx, h.Pool, "registration", session)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"session_id": sessionID, "publicKey": creation.Response})
}

// PasskeyRegisterVerify finishes that ceremony and stores the new
// credential. `device_label` is an optional query param (e.g. "MacBook
// Pro Touch ID") purely for the account's own passkey list -- it isn't
// used in verification. `session_id` (query param) is the id
// PasskeyRegisterOptions handed back.
func (h *Handlers) PasskeyRegisterVerify(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	sessionID := r.URL.Query().Get("session_id")
	if sessionID == "" {
		writeError(w, http.StatusBadRequest, "session_id query param is required")
		return
	}
	ctx := r.Context()
	user, err := loadWebauthnUser(ctx, h.Pool, claims.Subject, claims.Email, "")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	session, err := consumeWebauthnChallenge(ctx, h.Pool, sessionID, "registration")
	if err != nil {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}

	cred, err := h.WebAuthn.FinishRegistration(user, *session, r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "passkey registration could not be verified: "+err.Error())
		return
	}
	if err := storeWebauthnCredential(ctx, h.Pool, claims.Subject, cred, r.URL.Query().Get("device_label")); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) Me(w http.ResponseWriter, r *http.Request) {
	claims, ok := FromContext(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"user_id": claims.Subject,
		"org_id":  claims.OrgID,
		"role":    claims.Role,
		"email":   claims.Email,
	})
}

type ctxKey struct{}

func WithClaims(ctx context.Context, claims *Claims) context.Context {
	return context.WithValue(ctx, ctxKey{}, claims)
}

func FromContext(ctx context.Context) (*Claims, bool) {
	c, ok := ctx.Value(ctxKey{}).(*Claims)
	return c, ok
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
