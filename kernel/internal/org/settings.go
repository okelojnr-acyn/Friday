package org

import (
	"encoding/json"
	"net/http"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Settings is the organisation-wide configuration every app reads:
// GET /orgs/settings (any member), PUT /orgs/settings (owner or admin).
type Settings struct {
	Pool *pgxpool.Pool
}

type settingsView struct {
	Name             string `json:"name"`
	Currency         string `json:"currency"`
	TaxRateBP        int    `json:"tax_rate_bp"`
	PricesIncludeTax bool   `json:"prices_include_tax"`
}

var currencyRe = regexp.MustCompile(`^[A-Z]{3}$`)

func writeSettingsJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func (s *Settings) load(r *http.Request, orgID string) (settingsView, error) {
	var v settingsView
	err := s.Pool.QueryRow(r.Context(), `
		SELECT name, currency, tax_rate_bp, prices_include_tax FROM core.orgs WHERE id = $1`, orgID,
	).Scan(&v.Name, &v.Currency, &v.TaxRateBP, &v.PricesIncludeTax)
	return v, err
}

func (s *Settings) Get(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	v, err := s.load(r, claims.OrgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusNotFound, map[string]string{"error": "organisation not found"})
		return
	}
	writeSettingsJSON(w, http.StatusOK, v)
}

func (s *Settings) Put(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return
	}
	if claims.Via != "" || (claims.Role != "owner" && claims.Role != "admin") {
		writeSettingsJSON(w, http.StatusForbidden, map[string]string{"error": "only owners and admins change organisation settings"})
		return
	}
	var req struct {
		Currency         *string `json:"currency"`
		TaxRateBP        *int    `json:"tax_rate_bp"`
		PricesIncludeTax *bool   `json:"prices_include_tax"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&req); err != nil {
		writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}
	if req.Currency != nil {
		c := strings.ToUpper(strings.TrimSpace(*req.Currency))
		if !currencyRe.MatchString(c) {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "currency is a 3-letter code like KES, UGX, TZS or USD"})
			return
		}
		req.Currency = &c
	}
	if req.TaxRateBP != nil && (*req.TaxRateBP < 0 || *req.TaxRateBP > 5000) {
		writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "tax rate must be between 0% and 50%"})
		return
	}
	if _, err := s.Pool.Exec(r.Context(), `
		UPDATE core.orgs SET currency = COALESCE($2, currency), tax_rate_bp = COALESCE($3, tax_rate_bp),
		       prices_include_tax = COALESCE($4, prices_include_tax)
		WHERE id = $1`, claims.OrgID, req.Currency, req.TaxRateBP, req.PricesIncludeTax); err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not save the settings"})
		return
	}
	v, err := s.load(r, claims.OrgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not read the settings"})
		return
	}
	writeSettingsJSON(w, http.StatusOK, v)
}
