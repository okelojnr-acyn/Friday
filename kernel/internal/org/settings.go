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
	Name             string     `json:"name"`
	Currency         string     `json:"currency"`
	TaxRateBP        int        `json:"tax_rate_bp"`
	PricesIncludeTax bool       `json:"prices_include_tax"`
	Tax              TaxProfile `json:"tax"`
	// What the business takes; tills offer these unless set otherwise.
	PaymentMethods []string `json:"payment_methods"`
	// The online store's look (Store settings).
	Storefront Storefront `json:"storefront"`
	// The business's time zone: its days, months and books ("" = not set, UTC).
	TimeZone string `json:"time_zone"`
	// The usual currency there ("" when none), for Business settings to offer.
	SuggestedCurrency string `json:"suggested_currency"`
}

// PaymentMethods a business can offer; invoicing's registers.py keeps
// the same list for a till's own choice.
var PaymentMethods = []string{"cash", "mpesa", "card", "paystack", "pesapal"}

// normalizePaymentMethods drops repeats and refuses unknown or no methods.
func normalizePaymentMethods(in []string) ([]string, string) {
	known := map[string]bool{}
	for _, m := range PaymentMethods {
		known[m] = true
	}
	out := []string{}
	seen := map[string]bool{}
	for _, m := range in {
		m = strings.ToLower(strings.TrimSpace(m))
		if !known[m] {
			return nil, "payment methods are some of " + strings.Join(PaymentMethods, ", ")
		}
		if !seen[m] {
			seen[m] = true
			out = append(out, m)
		}
	}
	if len(out) == 0 {
		return nil, "keep at least one payment method"
	}
	return out, ""
}

// TaxRate is one rate a business uses. Code follows KRA's eTIMS tax
// types (A exempt, B 16%, C zero-rated, D non-VAT, E 8%) so a sale can
// be reported without a second mapping.
type TaxRate struct {
	Code   string `json:"code"`
	Name   string `json:"name"`
	RateBP int    `json:"rate_bp"`
}

// TaxProfile is the Tax section of Business settings (core.orgs.tax_profile).
// tax_rate_bp, which the till charges, follows from it: the default
// rate when the business is VAT-registered, else 0.
type TaxProfile struct {
	VATRegistered        bool      `json:"vat_registered"`
	TaxPIN               string    `json:"tax_pin"`
	DefaultCode          string    `json:"default_code"`
	Rates                []TaxRate `json:"rates"`
	ReceiptShowPIN       bool      `json:"receipt_show_pin"`
	ReceiptShowBreakdown bool      `json:"receipt_show_breakdown"`
	ReceiptFooter        string    `json:"receipt_footer"`
	// Printed under the business name on every receipt.
	ReceiptAddress string `json:"receipt_address"`
	ReceiptPhone   string `json:"receipt_phone"`
}

// DefaultTaxProfile suits a Kenyan shop. Orgs saved before tax_profile
// existed read as this, merged with whatever they stored.
func DefaultTaxProfile() TaxProfile {
	return TaxProfile{
		VATRegistered: true,
		DefaultCode:   "B",
		Rates: []TaxRate{
			{Code: "A", Name: "Exempt", RateBP: 0},
			{Code: "B", Name: "Standard VAT", RateBP: 1600},
			{Code: "C", Name: "Zero-rated", RateBP: 0},
			{Code: "D", Name: "Non-VAT", RateBP: 0},
			{Code: "E", Name: "Reduced VAT", RateBP: 800},
		},
		ReceiptShowPIN:       true,
		ReceiptShowBreakdown: true,
	}
}

var (
	currencyRe = regexp.MustCompile(`^[A-Z]{3}$`)
	taxCodeRe  = regexp.MustCompile(`^[A-Z0-9]{1,4}$`)
	taxPINRe   = regexp.MustCompile(`^[A-Z0-9-]{1,20}$`)
	kraPINRe   = regexp.MustCompile(`^[AP][0-9]{9}[A-Z]$`)
)

func (p *TaxProfile) defaultRate() (TaxRate, bool) {
	for _, r := range p.Rates {
		if r.Code == p.DefaultCode {
			return r, true
		}
	}
	return TaxRate{}, false
}

// tillRateBP is what the till charges under this profile.
func (p *TaxProfile) tillRateBP() int {
	if !p.VATRegistered {
		return 0
	}
	r, _ := p.defaultRate()
	return r.RateBP
}

// normalize trims and checks a profile; the message suits an owner.
func (p *TaxProfile) normalize(currency string) string {
	p.TaxPIN = strings.ToUpper(strings.TrimSpace(p.TaxPIN))
	if p.TaxPIN != "" {
		if !taxPINRe.MatchString(p.TaxPIN) {
			return "the tax PIN is letters and digits only, up to 20"
		}
		if currency == "KES" && !kraPINRe.MatchString(p.TaxPIN) {
			return "a KRA PIN looks like P051234567X: A or P, nine digits, a letter"
		}
	}
	if p.VATRegistered && p.TaxPIN == "" {
		return "a VAT-registered business needs its tax PIN"
	}
	if len(p.Rates) == 0 || len(p.Rates) > 20 {
		return "keep between 1 and 20 tax rates"
	}
	seen := map[string]bool{}
	for i := range p.Rates {
		r := &p.Rates[i]
		r.Code = strings.ToUpper(strings.TrimSpace(r.Code))
		r.Name = strings.TrimSpace(r.Name)
		if !taxCodeRe.MatchString(r.Code) {
			return "a tax code is 1 to 4 letters or digits, like B"
		}
		if seen[r.Code] {
			return "tax code " + r.Code + " is used twice"
		}
		seen[r.Code] = true
		if r.Name == "" || len(r.Name) > 40 {
			return "each tax rate needs a name (up to 40 characters)"
		}
		if r.RateBP < 0 || r.RateBP > 5000 {
			return "tax rates must be between 0% and 50%"
		}
	}
	p.DefaultCode = strings.ToUpper(strings.TrimSpace(p.DefaultCode))
	if _, ok := p.defaultRate(); !ok {
		return "choose which rate the till charges"
	}
	p.ReceiptAddress = strings.TrimSpace(p.ReceiptAddress)
	p.ReceiptPhone = strings.TrimSpace(p.ReceiptPhone)
	if len(p.ReceiptAddress) > 120 || len(p.ReceiptPhone) > 40 {
		return "the receipt address is up to 120 characters and the phone up to 40"
	}
	p.ReceiptFooter = strings.TrimSpace(p.ReceiptFooter)
	if len(p.ReceiptFooter) > 200 {
		return "the receipt footer is up to 200 characters"
	}
	return ""
}

func writeSettingsJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func (s *Settings) load(r *http.Request, orgID string) (settingsView, error) {
	var v settingsView
	var raw, store []byte
	err := s.Pool.QueryRow(r.Context(), `
		SELECT name, currency, tax_rate_bp, prices_include_tax, tax_profile, payment_methods, storefront, time_zone FROM core.orgs WHERE id = $1`, orgID,
	).Scan(&v.Name, &v.Currency, &v.TaxRateBP, &v.PricesIncludeTax, &raw, &v.PaymentMethods, &store, &v.TimeZone)
	if err != nil {
		return v, err
	}
	if v.PaymentMethods == nil {
		v.PaymentMethods = PaymentMethods
	}
	v.Tax = DefaultTaxProfile()
	if len(raw) > 0 {
		json.Unmarshal(raw, &v.Tax) // fields stored win; missing ones keep the default
	}
	v.SuggestedCurrency = CurrencyForZone(v.TimeZone)
	v.Storefront = DefaultStorefront()
	json.Unmarshal(store, &v.Storefront)
	return v, nil
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
		Currency         *string     `json:"currency"`
		TaxRateBP        *int        `json:"tax_rate_bp"`
		PricesIncludeTax *bool       `json:"prices_include_tax"`
		Tax              *TaxProfile `json:"tax"`
		PaymentMethods   []string    `json:"payment_methods"`
		Storefront       *Storefront `json:"storefront"`
		TimeZone         *string     `json:"time_zone"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&req); err != nil {
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
	if req.PaymentMethods != nil {
		methods, msg := normalizePaymentMethods(req.PaymentMethods)
		if msg != "" {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
			return
		}
		req.PaymentMethods = methods
	}
	if req.TimeZone != nil && !validTimeZone(*req.TimeZone) {
		writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": "the time zone is a place name like Africa/Nairobi"})
		return
	}
	var storeJSON []byte
	if req.Storefront != nil {
		if msg := req.Storefront.normalize(); msg != "" {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
			return
		}
		storeJSON, _ = json.Marshal(req.Storefront)
	}
	var taxJSON []byte
	if req.Tax != nil {
		currency := ""
		if req.Currency != nil {
			currency = *req.Currency
		} else if cur, err := s.load(r, claims.OrgID); err == nil {
			currency = cur.Currency
		}
		if msg := req.Tax.normalize(currency); msg != "" {
			writeSettingsJSON(w, http.StatusBadRequest, map[string]string{"error": msg})
			return
		}
		bp := req.Tax.tillRateBP()
		req.TaxRateBP = &bp
		taxJSON, _ = json.Marshal(req.Tax)
	}
	if _, err := s.Pool.Exec(r.Context(), `
		UPDATE core.orgs SET currency = COALESCE($2, currency), tax_rate_bp = COALESCE($3, tax_rate_bp),
		       prices_include_tax = COALESCE($4, prices_include_tax), tax_profile = COALESCE($5, tax_profile),
		       payment_methods = COALESCE($6, payment_methods), storefront = COALESCE($7, storefront),
		       time_zone = COALESCE($8, time_zone)
		WHERE id = $1`, claims.OrgID, req.Currency, req.TaxRateBP, req.PricesIncludeTax, taxJSON, req.PaymentMethods, storeJSON, req.TimeZone); err != nil {
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
