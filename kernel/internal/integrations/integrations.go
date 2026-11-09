// Package integrations is the kernel's per-org store for third-party
// integration credentials (Stripe, Slack, Calendly, Acyn Wallet, ...).
// It's the one place an org admin configures an API key, and the one
// place an app service fetches that key back -- the same role this
// package plays for integrations that core.apps/core.app_installs plays
// for which apps an org has enabled. See INTEGRATIONS.md for the config
// shape each provider expects and ARCHITECTURE.md's "Integrations"
// section for how this fits the rest of the system.
package integrations

import (
	"encoding/json"
	"net/http"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

type Handlers struct {
	Pool          *pgxpool.Pool
	InternalToken string
	// JWTSecret and PublicURL are only used by the Google OAuth flow
	// (google_oauth.go) -- JWTSecret signs/verifies the state param
	// (same secret as session JWTs, different claims shape), PublicURL
	// builds the redirect_uri Google requires to match exactly between
	// the authorize and token-exchange steps. CORSOrigin is where the
	// callback redirects the browser back to when the flow finishes.
	JWTSecret  string
	PublicURL  string
	CORSOrigin string
}

type credentialView struct {
	Provider  string         `json:"provider"`
	Config    map[string]any `json:"config"`
	Connected bool           `json:"connected"`
}

// List returns which providers the calling org has configured -- the
// Integrations settings screen's "what's connected" view. Deliberately
// never includes `config` (unlike Get): any authenticated org member can
// call this, including a viewer, so a provider's secret (an API key)
// never leaves the server to a role that shouldn't see it. The settings
// screen calls the admin-gated Get for the one provider an admin is
// actually editing.
func (h *Handlers) List(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	rows, err := h.Pool.Query(r.Context(), `
		SELECT provider FROM core.integration_credentials WHERE org_id = $1
	`, claims.OrgID)
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	// []credentialView{}, not var out []credentialView -- a nil slice
	// encodes as JSON `null`, which crashed the frontend's `rows.map`
	// for every org with zero integrations connected (i.e. every fresh
	// org) until this was caught by live-testing the just-added Members
	// page right after creating a brand new test org.
	out := []credentialView{}
	for rows.Next() {
		var v credentialView
		if err := rows.Scan(&v.Provider); err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		v.Config = map[string]any{}
		v.Connected = true
		out = append(out, v)
	}
	writeJSON(w, http.StatusOK, out)
}

// Get returns one provider's stored config, for prefilling the settings
// form. Admin-only, same as Set/Delete -- a provider's config may itself
// be a secret (an API key), so this is scoped the same as any other
// admin-only write path even though it's a read.
func (h *Handlers) Get(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}
	provider := r.PathValue("provider")

	var raw []byte
	err := h.Pool.QueryRow(r.Context(), `
		SELECT config FROM core.integration_credentials WHERE org_id = $1 AND provider = $2
	`, claims.OrgID, provider).Scan(&raw)
	if err == pgx.ErrNoRows {
		writeJSON(w, http.StatusOK, credentialView{Provider: provider, Config: map[string]any{}, Connected: false})
		return
	}
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	var cfg map[string]any
	_ = json.Unmarshal(raw, &cfg)
	writeJSON(w, http.StatusOK, credentialView{Provider: provider, Config: cfg, Connected: true})
}

// Set upserts a provider's config -- "Connect" or "Save changes" on the
// Integrations settings screen.
func (h *Handlers) Set(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}
	provider := r.PathValue("provider")

	var cfg map[string]any
	if err := json.NewDecoder(r.Body).Decode(&cfg); err != nil {
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	raw, err := json.Marshal(cfg)
	if err != nil {
		http.Error(w, "invalid config", http.StatusBadRequest)
		return
	}

	if _, err := h.Pool.Exec(r.Context(), `
		INSERT INTO core.integration_credentials (org_id, provider, config, updated_at)
		VALUES ($1, $2, $3, now())
		ON CONFLICT (org_id, provider) DO UPDATE SET config = EXCLUDED.config, updated_at = now()
	`, claims.OrgID, provider, raw); err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, credentialView{Provider: provider, Config: cfg, Connected: true})
}

// Delete disconnects a provider -- "Disconnect" on the settings screen.
func (h *Handlers) Delete(w http.ResponseWriter, r *http.Request) {
	claims, ok := requireAdmin(w, r)
	if !ok {
		return
	}
	provider := r.PathValue("provider")
	if _, err := h.Pool.Exec(r.Context(), `
		DELETE FROM core.integration_credentials WHERE org_id = $1 AND provider = $2
	`, claims.OrgID, provider); err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// GetInternal is how an app service fetches an org's provider config --
// e.g. apps/invoicing resolving the org's Stripe secret key before
// creating a PaymentIntent. Guarded by the same shared kernel token
// gateway.EventsHandler already uses for the reverse direction (apps ->
// kernel event publish), not a per-request JWT, because this is a
// server-to-server call with no end-user request in flight.
func (h *Handlers) GetInternal(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Authorization") != "Bearer "+h.InternalToken {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	orgID := r.PathValue("org_id")
	provider := r.PathValue("provider")

	var raw []byte
	err := h.Pool.QueryRow(r.Context(), `
		SELECT config FROM core.integration_credentials WHERE org_id = $1 AND provider = $2
	`, orgID, provider).Scan(&raw)
	if err == pgx.ErrNoRows {
		writeJSON(w, http.StatusOK, map[string]any{})
		return
	}
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	var cfg map[string]any
	_ = json.Unmarshal(raw, &cfg)
	writeJSON(w, http.StatusOK, cfg)
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

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
