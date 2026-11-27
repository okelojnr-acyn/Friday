package org

import (
	"encoding/json"
	"net/http"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/svcauth"
)

// SpendingPolicy is how a business controls spending (docs/SPENDING-PLAN.md
// in Friday Host): when to ask first, when a written reason may stand in
// for a receipt, the tolerance over an approval, and petty cash. Amounts
// are in the business's cents (core.orgs.spending_policy). A business
// picks one of three presets and may change any number ("custom").
type SpendingPolicy struct {
	Preset string `json:"preset"`
	// Ask first above these, per spend (0 = always ask). Owners and
	// admins never need to.
	AskFirstMember        int64 `json:"ask_first_member"`
	AskFirstTeamLeader    int64 `json:"ask_first_team_leader"`
	AskFirstBranchManager int64 `json:"ask_first_branch_manager"`
	TripsAskFirst         bool  `json:"trips_ask_first"`
	// A written reason instead of a receipt, under this amount, at most
	// this many times per person in 12 months.
	NoReceiptUnder   int64 `json:"no_receipt_under"`
	NoReceiptPerYear int   `json:"no_receipt_per_year"`
	// Flag a claim over its approval by more than this percent.
	TolerancePct int   `json:"tolerance_pct"`
	TillPayouts  bool  `json:"till_payouts"`
	PettyFloat   int64 `json:"petty_float"`
	PettySlipMax int64 `json:"petty_slip_max"`
	// At the till, a discount of this percent or more (or a price below
	// the shelf) needs a team leader's or manager's PIN. 0: every one does.
	TillDiscountPct int `json:"till_discount_pct"`
}

// SpendingPresets: Simple (a small shop), Standard (the default: receipts
// always, missing-receipt notes for small amounts three times a year, one
// petty cash slip at most a fifth of the float, a separate float rather
// than the till, 10% tolerance), Strict (a larger business). KES amounts.
var SpendingPresets = map[string]SpendingPolicy{
	"simple": {Preset: "simple", AskFirstMember: 500_000, AskFirstTeamLeader: 2_000_000, AskFirstBranchManager: 10_000_000,
		TripsAskFirst: true, NoReceiptUnder: 200_000, NoReceiptPerYear: 6, TolerancePct: 15, TillPayouts: true,
		PettyFloat: 2_000_000, PettySlipMax: 500_000, TillDiscountPct: 15},
	"standard": {Preset: "standard", AskFirstMember: 200_000, AskFirstTeamLeader: 1_000_000, AskFirstBranchManager: 5_000_000,
		TripsAskFirst: true, NoReceiptUnder: 100_000, NoReceiptPerYear: 3, TolerancePct: 10, TillPayouts: false,
		PettyFloat: 1_000_000, PettySlipMax: 200_000, TillDiscountPct: 10},
	"strict": {Preset: "strict", AskFirstMember: 100_000, AskFirstTeamLeader: 500_000, AskFirstBranchManager: 2_000_000,
		TripsAskFirst: true, NoReceiptUnder: 50_000, NoReceiptPerYear: 2, TolerancePct: 5, TillPayouts: false,
		PettyFloat: 1_000_000, PettySlipMax: 100_000, TillDiscountPct: 5},
}

func (s SpendingPolicy) valid() bool {
	const most = 1_000_000_000_00
	for _, v := range []int64{s.AskFirstMember, s.AskFirstTeamLeader, s.AskFirstBranchManager, s.NoReceiptUnder, s.PettyFloat, s.PettySlipMax} {
		if v < 0 || v > most {
			return false
		}
	}
	return s.NoReceiptPerYear >= 0 && s.NoReceiptPerYear <= 52 && s.TolerancePct >= 0 && s.TolerancePct <= 100 &&
		s.TillDiscountPct >= 0 && s.TillDiscountPct <= 100 &&
		s.PettySlipMax <= s.PettyFloat
}

func (p *People) spending(r *http.Request, orgID string) (SpendingPolicy, error) {
	var raw []byte
	s := SpendingPresets["standard"]
	if err := p.Pool.QueryRow(r.Context(), `SELECT spending_policy FROM core.orgs WHERE id::text = $1`, orgID).Scan(&raw); err != nil {
		return s, err
	}
	json.Unmarshal(raw, &s) // stored fields win; missing ones keep Standard
	return s, nil
}

type spendingView struct {
	SpendingPolicy
	Presets map[string]SpendingPolicy `json:"presets"`
}

// GetSpendingPolicy (GET /orgs/spending-policy): any member (staff see
// the rules they spend under), with the three presets for Settings.
func (p *People) GetSpendingPolicy(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	s, err := p.spending(r, c.OrgID)
	if err != nil {
		peopleError(w, http.StatusNotFound, "organisation not found")
		return
	}
	peopleJSON(w, http.StatusOK, spendingView{s, SpendingPresets})
}

// PutSpendingPolicy (PUT /orgs/spending-policy): owners and admins. A
// preset name alone takes that preset's numbers; "custom" keeps the
// numbers sent.
func (p *People) PutSpendingPolicy(w http.ResponseWriter, r *http.Request) {
	c, ok := auth.FromContext(r.Context())
	if !ok {
		peopleError(w, http.StatusUnauthorized, "missing or invalid token")
		return
	}
	if c.Via != "" || (c.Role != "owner" && c.Role != "admin") {
		peopleError(w, http.StatusForbidden, "only owners and admins set the spending policy")
		return
	}
	var s SpendingPolicy
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&s); err != nil {
		peopleError(w, http.StatusBadRequest, "send a spending policy")
		return
	}
	if preset, ok := SpendingPresets[s.Preset]; ok {
		s = preset
	} else {
		s.Preset = "custom"
	}
	if !s.valid() {
		peopleError(w, http.StatusBadRequest, "amounts are 0 or more, a slip can't be more than the float, the tolerance is 0 to 100%")
		return
	}
	raw, _ := json.Marshal(s)
	if _, err := p.Pool.Exec(r.Context(), `UPDATE core.orgs SET spending_policy = $2 WHERE id::text = $1`, c.OrgID, raw); err != nil {
		peopleError(w, http.StatusInternalServerError, "couldn't save the spending policy")
		return
	}
	peopleJSON(w, http.StatusOK, spendingView{s, SpendingPresets})
}

// SpendingPolicyFor (GET /internal/people/{org_id}/spending-policy): apps.
func (p *People) SpendingPolicyFor(w http.ResponseWriter, r *http.Request) {
	if !svcauth.Bearer(r, p.InternalToken) {
		peopleError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	s, err := p.spending(r, r.PathValue("org_id"))
	if err != nil {
		peopleError(w, http.StatusNotFound, "organisation not found")
		return
	}
	peopleJSON(w, http.StatusOK, s)
}
