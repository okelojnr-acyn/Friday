package org

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
)

// validTimeZone: an IANA name Go knows ("Africa/Nairobi"); the kernel
// embeds the zone database (time/tzdata), so this doesn't depend on the image.
func validTimeZone(tz string) bool {
	if tz == "" || len(tz) > 64 || tz == "Local" {
		return false
	}
	_, err := time.LoadLocation(tz)
	return err == nil
}

// zoneCurrency: the usual currency where a time zone is, for a new
// business's default. Only currencies Business settings lists; elsewhere
// the default (KES) stays and the owner picks.
var zoneCurrency = map[string]string{
	"Africa/Nairobi": "KES", "Africa/Kampala": "UGX", "Africa/Dar_es_Salaam": "TZS", "Africa/Kigali": "RWF",
	"Africa/Addis_Ababa": "ETB", "Africa/Lagos": "NGN", "Africa/Accra": "GHS", "Africa/Johannesburg": "ZAR",
	"Europe/London": "GBP", "Europe/Dublin": "EUR", "Europe/Paris": "EUR", "Europe/Berlin": "EUR",
	"Europe/Madrid": "EUR", "Europe/Rome": "EUR", "Europe/Amsterdam": "EUR", "Europe/Brussels": "EUR",
	"Europe/Lisbon": "EUR", "Europe/Vienna": "EUR",
}

// CurrencyForZone is the suggestion for a time zone ("" when none).
func CurrencyForZone(tz string) string {
	if c, ok := zoneCurrency[tz]; ok {
		return c
	}
	if strings.HasPrefix(tz, "America/") || strings.HasPrefix(tz, "US/") {
		return "USD"
	}
	return ""
}

// SetMyTimeZone (PUT /auth/me/time-zone, {"time_zone"}): the web sends the
// browser's zone after sign-in. It's the person's own; and when the business
// has none yet, an owner's or admin's also becomes the business's, with that
// place's currency if the business is brand new (under a day old, before
// anything is recorded in another currency).
func (p *People) SetMyTimeZone(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	var req struct {
		TimeZone string `json:"time_zone"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<10)).Decode(&req); err != nil || !validTimeZone(req.TimeZone) {
		peopleError(w, http.StatusBadRequest, "time_zone is a place name like Africa/Nairobi")
		return
	}
	ctx := r.Context()
	if _, err := p.Pool.Exec(ctx, `UPDATE core.users SET time_zone = $2 WHERE id::text = $1`, c.Subject, req.TimeZone); err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't save the time zone")
		return
	}
	if c.Via == "" && (c.Role == "owner" || c.Role == "admin") {
		cur := CurrencyForZone(req.TimeZone)
		if _, err := p.Pool.Exec(ctx, `
			UPDATE core.orgs SET time_zone = $2,
			       currency = CASE WHEN $3 <> '' AND created_at > now() - interval '1 day' THEN $3 ELSE currency END
			WHERE id::text = $1 AND time_zone = ''`, c.OrgID, req.TimeZone, cur); err != nil {
			peopleError(w, http.StatusInternalServerError, "couldn't save the time zone")
			return
		}
	}
	var orgTZ, currency string
	_ = p.Pool.QueryRow(ctx, `SELECT time_zone, currency FROM core.orgs WHERE id::text = $1`, c.OrgID).Scan(&orgTZ, &currency)
	peopleJSON(w, http.StatusOK, map[string]string{"time_zone": req.TimeZone, "org_time_zone": orgTZ, "currency": currency})
}

// OrgTimeZone (GET /internal/orgs/{org_id}/time-zone): the business's zone
// for apps' days and months ("" = not set: UTC). Apps only.
func (p *People) OrgTimeZone(w http.ResponseWriter, r *http.Request) {
	if !svcauth.Bearer(r, p.InternalToken) {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var tz string
	if err := p.Pool.QueryRow(r.Context(), `SELECT time_zone FROM core.orgs WHERE id::text = $1`, r.PathValue("org_id")).Scan(&tz); err != nil {
		peopleError(w, http.StatusNotFound, "organisation not found")
		return
	}
	peopleJSON(w, http.StatusOK, map[string]string{"time_zone": tz})
}
