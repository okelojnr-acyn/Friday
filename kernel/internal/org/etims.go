package org

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
)

// Etims is the eTIMS section of Business settings: how this business
// reaches KRA's electronic tax invoice system. GET and PUT /orgs/etims,
// owners and admins only. The CMC key KRA issues at device
// initialisation is a credential: it is stored, never sent back
// (cmc_key_set says whether there is one).
type Etims struct {
	Pool *pgxpool.Pool
	// InternalToken guards GET /internal/etims/{org_id}, which the
	// Invoicing app reads (with the CMC key) to talk to KRA.
	InternalToken string
	// Automation is on only when the server sets ETIMS_AUTOMATION=1
	// (after the production checks). Until then sales are filed by hand
	// in KRA's eTIMS portal and "enabled" cannot be switched on.
	Automation bool
}

type etimsView struct {
	Enabled      bool   `json:"enabled"`
	Environment  string `json:"environment"`
	Mode         string `json:"mode"`
	BranchID     string `json:"branch_id"`
	DeviceSerial string `json:"device_serial"`
	VSCUURL      string `json:"vscu_url"`
	CMCKeySet    bool   `json:"cmc_key_set"`
	// AutomationAvailable: this server may send sales to KRA itself.
	AutomationAvailable bool       `json:"automation_available"`
	UpdatedAt           *time.Time `json:"updated_at"`
	// From Tax settings, shown so the owner sees what KRA will be told.
	TaxPIN string `json:"tax_pin"`
}

var (
	branchIDRe     = regexp.MustCompile(`^[0-9]{2}$`)
	deviceSerialRe = regexp.MustCompile(`^[A-Za-z0-9_-]{1,40}$`)
)

func etimsCaller(w http.ResponseWriter, r *http.Request) (string, bool) {
	claims, ok := auth.FromContext(r.Context())
	if !ok {
		writeSettingsJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing or invalid token"})
		return "", false
	}
	if claims.Via != "" || (claims.Role != "owner" && claims.Role != "admin") {
		writeSettingsJSON(w, http.StatusForbidden, map[string]string{"error": "only owners and admins see eTIMS settings"})
		return "", false
	}
	return claims.OrgID, true
}

func (e *Etims) load(r *http.Request, orgID string) (etimsView, error) {
	v := etimsView{Environment: "sandbox", Mode: "oscu", BranchID: "00", AutomationAvailable: e.Automation}
	var cmc string
	var updated time.Time
	err := e.Pool.QueryRow(r.Context(), `
		SELECT enabled, environment, mode, branch_id, device_serial, vscu_url, cmc_key, updated_at
		FROM core.org_etims WHERE org_id = $1`, orgID,
	).Scan(&v.Enabled, &v.Environment, &v.Mode, &v.BranchID, &v.DeviceSerial, &v.VSCUURL, &cmc, &updated)
	switch {
	case err == pgx.ErrNoRows:
	case err != nil:
		return v, err
	default:
		v.CMCKeySet = cmc != ""
		v.UpdatedAt = &updated
	}
	var raw []byte
	if err := e.Pool.QueryRow(r.Context(), `SELECT tax_profile FROM core.orgs WHERE id = $1`, orgID).Scan(&raw); err != nil {
		return v, err
	}
	tax := DefaultTaxProfile()
	json.Unmarshal(raw, &tax)
	v.TaxPIN = tax.TaxPIN
	return v, nil
}

func (e *Etims) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := etimsCaller(w, r)
	if !ok {
		return
	}
	v, err := e.load(r, orgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not read the eTIMS settings"})
		return
	}
	writeSettingsJSON(w, http.StatusOK, v)
}

func (e *Etims) Put(w http.ResponseWriter, r *http.Request) {
	orgID, ok := etimsCaller(w, r)
	if !ok {
		return
	}
	var req struct {
		Enabled      *bool   `json:"enabled"`
		Environment  *string `json:"environment"`
		Mode         *string `json:"mode"`
		BranchID     *string `json:"branch_id"`
		DeviceSerial *string `json:"device_serial"`
		VSCUURL      *string `json:"vscu_url"`
		CMCKey       *string `json:"cmc_key"`
		ClearCMCKey  bool    `json:"clear_cmc_key"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil {
		writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}
	cur, err := e.load(r, orgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not read the eTIMS settings"})
		return
	}
	bad := func(msg string) {
		writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
	}
	if req.Enabled != nil {
		cur.Enabled = *req.Enabled
	}
	if req.Environment != nil {
		cur.Environment = strings.TrimSpace(*req.Environment)
	}
	if cur.Environment != "sandbox" && cur.Environment != "production" {
		bad("environment is sandbox or production")
		return
	}
	if req.Mode != nil {
		cur.Mode = strings.ToLower(strings.TrimSpace(*req.Mode))
	}
	if cur.Mode != "oscu" && cur.Mode != "vscu" {
		bad("mode is OSCU (online) or VSCU (virtual sales control unit)")
		return
	}
	if req.BranchID != nil {
		cur.BranchID = strings.TrimSpace(*req.BranchID)
	}
	if !branchIDRe.MatchString(cur.BranchID) {
		bad("the branch ID is two digits; the head office is 00")
		return
	}
	if req.DeviceSerial != nil {
		cur.DeviceSerial = strings.TrimSpace(*req.DeviceSerial)
	}
	if cur.DeviceSerial != "" && !deviceSerialRe.MatchString(cur.DeviceSerial) {
		bad("the device serial is letters, digits, - and _, up to 40")
		return
	}
	if req.VSCUURL != nil {
		cur.VSCUURL = strings.TrimSpace(*req.VSCUURL)
	}
	if cur.VSCUURL != "" {
		u, err := url.Parse(cur.VSCUURL)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			bad("the VSCU address is a URL like http://192.168.1.20:8088")
			return
		}
	}
	var cmc *string
	if req.ClearCMCKey {
		empty := ""
		cmc = &empty
		cur.CMCKeySet = false
	} else if req.CMCKey != nil && strings.TrimSpace(*req.CMCKey) != "" {
		k := strings.TrimSpace(*req.CMCKey)
		if len(k) > 200 {
			bad("the CMC key is too long")
			return
		}
		cmc = &k
		cur.CMCKeySet = true
	}
	if cur.Enabled && !e.Automation {
		bad("sending sales to KRA automatically is not switched on for this server yet; file them in the eTIMS portal and record each invoice number in Friday")
		return
	}
	if cur.Enabled {
		switch {
		case cur.TaxPIN == "":
			bad("add the business's KRA PIN under Tax first")
			return
		case cur.DeviceSerial == "":
			bad("add the device serial number KRA approved")
			return
		case cur.Mode == "vscu" && cur.VSCUURL == "":
			bad("VSCU needs the address of the VSCU on your network")
			return
		}
	}
	if _, err := e.Pool.Exec(r.Context(), `
		INSERT INTO core.org_etims (org_id, enabled, environment, mode, branch_id, device_serial, vscu_url, cmc_key, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, COALESCE($8, ''), now())
		ON CONFLICT (org_id) DO UPDATE SET enabled = $2, environment = $3, mode = $4, branch_id = $5,
		       device_serial = $6, vscu_url = $7, cmc_key = COALESCE($8, core.org_etims.cmc_key), updated_at = now()`,
		orgID, cur.Enabled, cur.Environment, cur.Mode, cur.BranchID, cur.DeviceSerial, cur.VSCUURL, cmc); err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not save the eTIMS settings"})
		return
	}
	v, err := e.load(r, orgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not read the eTIMS settings"})
		return
	}
	writeSettingsJSON(w, http.StatusOK, v)
}

// GetInternal serves the full eTIMS configuration, CMC key included, to
// Friday's own apps (Bearer KERNEL_EVENTS_TOKEN), never to a browser.
func (e *Etims) GetInternal(w http.ResponseWriter, r *http.Request) {
	if e.InternalToken == "" || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+e.InternalToken)) != 1 {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	orgID := r.PathValue("org_id")
	v, err := e.load(r, orgID)
	if err != nil {
		writeSettingsJSON(w, http.StatusNotFound, map[string]string{"error": "organisation not found"})
		return
	}
	var cmc, name string
	var raw []byte
	var inclusive bool
	e.Pool.QueryRow(r.Context(), `SELECT cmc_key FROM core.org_etims WHERE org_id = $1`, orgID).Scan(&cmc)
	e.Pool.QueryRow(r.Context(), `SELECT name, tax_profile, prices_include_tax FROM core.orgs WHERE id = $1`, orgID).Scan(&name, &raw, &inclusive)
	tax := DefaultTaxProfile()
	json.Unmarshal(raw, &tax)
	writeSettingsJSON(w, http.StatusOK, map[string]any{
		"enabled":              v.Enabled && e.Automation,
		"environment":          v.Environment,
		"mode":                 v.Mode,
		"branch_id":            v.BranchID,
		"device_serial":        v.DeviceSerial,
		"vscu_url":             v.VSCUURL,
		"cmc_key":              cmc,
		"tax_pin":              v.TaxPIN,
		"business_name":        name,
		"vat_registered":       tax.VATRegistered,
		"default_code":         tax.DefaultCode,
		"rates":                tax.Rates,
		"prices_include_tax":   inclusive,
		"automation_available": e.Automation,
	})
}
