package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

type Handlers struct {
	Pool   *pgxpool.Pool
	Issuer *Issuer
}

type registerRequest struct {
	OrgName  string `json:"org_name"`
	Email    string `json:"email"`
	Password string `json:"password"`
	FullName string `json:"full_name"`
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type authResponse struct {
	Token string `json:"token"`
	OrgID string `json:"org_id"`
	Role  string `json:"role"`
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

func slugify(name string) string {
	s := slugRe.ReplaceAllString(strings.ToLower(strings.TrimSpace(name)), "-")
	return strings.Trim(s, "-")
}

// Register creates a new org plus its first user (role=owner) in one call
// -- the common solo/small-business signup path. Inviting teammates into
// an existing org is a separate, smaller endpoint (POST /orgs/invite),
// not bundled here.
func (h *Handlers) Register(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.OrgName == "" || req.Email == "" || len(req.Password) < 8 {
		writeError(w, http.StatusBadRequest, "org_name, email required; password must be 8+ chars")
		return
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not hash password")
		return
	}

	ctx := r.Context()
	tx, err := h.Pool.Begin(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer tx.Rollback(ctx)

	var orgID string
	slug := slugify(req.OrgName)
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.orgs (name, slug) VALUES ($1, $2) RETURNING id`,
		req.OrgName, slug,
	).Scan(&orgID); err != nil {
		writeError(w, http.StatusConflict, "an org with that name already exists")
		return
	}

	var userID string
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.users (email, password_hash, full_name) VALUES ($1, $2, $3) RETURNING id`,
		req.Email, string(hash), req.FullName,
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

	token, err := h.Issuer.Issue(userID, orgID, "owner", req.Email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusCreated, authResponse{Token: token, OrgID: orgID, Role: "owner"})
}

func (h *Handlers) Login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	ctx := r.Context()
	var userID, passwordHash string
	if err := h.Pool.QueryRow(ctx,
		`SELECT id, password_hash FROM core.users WHERE email = $1`, req.Email,
	).Scan(&userID, &passwordHash); err != nil {
		if err == pgx.ErrNoRows {
			writeError(w, http.StatusUnauthorized, "invalid email or password")
			return
		}
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	if bcrypt.CompareHashAndPassword([]byte(passwordHash), []byte(req.Password)) != nil {
		writeError(w, http.StatusUnauthorized, "invalid email or password")
		return
	}

	var orgID, role string
	if err := h.Pool.QueryRow(ctx,
		`SELECT org_id, role FROM core.memberships WHERE user_id = $1 ORDER BY created_at LIMIT 1`,
		userID,
	).Scan(&orgID, &role); err != nil {
		writeError(w, http.StatusForbidden, "user has no org membership")
		return
	}

	token, err := h.Issuer.Issue(userID, orgID, role, req.Email)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not issue token")
		return
	}
	writeJSON(w, http.StatusOK, authResponse{Token: token, OrgID: orgID, Role: role})
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
