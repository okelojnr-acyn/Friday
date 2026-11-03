// Package org handles the apps-catalog: which apps exist in this
// deployment (seeded from the registry) and which ones a given org has
// enabled. This is what the home-screen launcher and the "Apps" settings
// screen both read from.
package org

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

type Catalog struct {
	Pool *pgxpool.Pool
	Apps []registry.App
}

// SeedApps upserts the registry's app list into core.apps so the catalog
// table always reflects what's actually deployed, even after a redeploy
// adds or removes an app.
func (c *Catalog) SeedApps(ctx context.Context) error {
	for _, a := range c.Apps {
		if _, err := c.Pool.Exec(ctx, `
			INSERT INTO core.apps (name, label, description, icon, category)
			VALUES ($1, $2, $3, $4, $5)
			ON CONFLICT (name) DO UPDATE SET
				label = EXCLUDED.label,
				description = EXCLUDED.description,
				icon = EXCLUDED.icon,
				category = EXCLUDED.category
		`, a.Name, a.Label, a.Description, a.Icon, a.Category); err != nil {
			return err
		}
	}
	return nil
}

type appView struct {
	Name        string `json:"name"`
	Label       string `json:"label"`
	Description string `json:"description"`
	Icon        string `json:"icon"`
	Category    string `json:"category"`
	Installed   bool   `json:"installed"`
}

func (c *Catalog) List(w http.ResponseWriter, r *http.Request) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	rows, err := c.Pool.Query(r.Context(), `
		SELECT a.name, a.label, a.description, a.icon, a.category,
		       (ai.org_id IS NOT NULL) AS installed
		FROM core.apps a
		LEFT JOIN core.app_installs ai
		  ON ai.app_name = a.name AND ai.org_id = $1
		ORDER BY a.category, a.label
	`, claims.OrgID)
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	// []appView{}, not var apps []appView -- a nil slice encodes as JSON
	// `null`, which would crash any frontend list.map() call (see the
	// identical bug this fixed in internal/integrations/integrations.go's
	// List). Every app is always seeded at startup so this can't happen
	// in practice today, but the fix costs nothing and the failure mode
	// if it ever did is a silently-stuck loading spinner, not an error.
	apps := []appView{}
	for rows.Next() {
		var a appView
		if err := rows.Scan(&a.Name, &a.Label, &a.Description, &a.Icon, &a.Category, &a.Installed); err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		apps = append(apps, a)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(apps)
}

func (c *Catalog) SetInstalled(installed bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		claims, ok := auth.FromContext(r.Context())
		if !ok {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if !(claims.Role == "owner" || claims.Role == "admin") {
			http.Error(w, "requires admin or owner", http.StatusForbidden)
			return
		}
		appName := r.PathValue("app")

		var err error
		if installed {
			_, err = c.Pool.Exec(r.Context(), `
				INSERT INTO core.app_installs (org_id, app_name) VALUES ($1, $2)
				ON CONFLICT DO NOTHING
			`, claims.OrgID, appName)
		} else {
			_, err = c.Pool.Exec(r.Context(), `
				DELETE FROM core.app_installs WHERE org_id = $1 AND app_name = $2
			`, claims.OrgID, appName)
		}
		if err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}
