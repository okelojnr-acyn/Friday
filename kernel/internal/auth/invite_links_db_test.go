package auth

// Invite links (plan section 12.6, step 3) against a real Postgres.

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"slices"
	"testing"
	"time"
)

func TestInviteLinks(t *testing.T) {
	pool := testPool(t)
	h := testHandlers(t, pool)
	h.Issuer = NewIssuer("test-secret-test-secret-test-secret", time.Hour)
	h.WebURL = "https://friday.example"
	ctx := context.Background()
	orgID := newOrg(t, pool)
	ownerEmail := "owner-" + randHex(4) + "@example.com"
	ownerID, err := h.joinOrg(ctx, ownerEmail, "Owner", orgID, "owner")
	if err != nil {
		t.Fatal(err)
	}
	owner := claimsFor(ownerID, orgID, ownerEmail)
	var mainLoc, westLoc string
	if err := pool.QueryRow(ctx, `SELECT id::text FROM core.locations WHERE org_id = $1 AND name = 'Main'`, orgID).Scan(&mainLoc); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `INSERT INTO core.locations (org_id, name) VALUES ($1, 'West') RETURNING id::text`, orgID).Scan(&westLoc); err != nil {
		t.Fatal(err)
	}

	invite := func(c *Claims, body map[string]any) (int, inviteView) {
		w := doJSON(t, h.CreateInvite, http.MethodPost, "/orgs/invites", c, nil, body, nil)
		var v inviteView
		json.Unmarshal(w.Body.Bytes(), &v)
		return w.Code, v
	}
	tokenOf := func(link string) string {
		u, err := url.Parse(link)
		if err != nil {
			t.Fatal(err)
		}
		return u.Query().Get("invite")
	}

	// An owner invites a cashier at West, reporting to the owner.
	email := "sam-" + randHex(4) + "@example.com"
	code, v := invite(owner, map[string]any{"email": email, "full_name": "Sam", "role": "member",
		"perms": []string{"cashier"}, "locations": []string{westLoc}, "reports_to": ownerID})
	if code != http.StatusCreated || v.Status != "pending" || v.Link == "" {
		t.Fatalf("invite: %d %+v", code, v)
	}
	token := tokenOf(v.Link)

	w := doJSON(t, h.PreviewInvite, http.MethodGet, "/invites/x", nil, nil, nil, map[string]string{"token": token})
	if w.Code != 200 {
		t.Fatalf("preview: %d %s", w.Code, w.Body.String())
	}
	w = doJSON(t, h.AcceptInviteLink, http.MethodPost, "/invites/x/accept", nil, nil, map[string]string{"full_name": "Sam K"}, map[string]string{"token": token})
	if w.Code != http.StatusCreated {
		t.Fatalf("accept: %d %s", w.Code, w.Body.String())
	}
	var role, name, staffID string
	var perms []string
	var reportsTo *string
	if err := pool.QueryRow(ctx, `
		SELECT m.role, m.perms, m.reports_to::text, m.staff_id, u.full_name FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE m.org_id = $1 AND u.email = $2`, orgID, email).Scan(&role, &perms, &reportsTo, &staffID, &name); err != nil {
		t.Fatal(err)
	}
	var locs []string
	rows, _ := pool.Query(ctx, `SELECT location_id::text FROM core.membership_locations ml JOIN core.users u ON u.id = ml.user_id WHERE u.email = $1`, email)
	for rows.Next() {
		var l string
		rows.Scan(&l)
		locs = append(locs, l)
	}
	rows.Close()
	if role != "member" || !slices.Equal(perms, []string{"cashier"}) || reportsTo == nil || *reportsTo != ownerID ||
		!slices.Equal(locs, []string{westLoc}) || name != "Sam K" || staffID == "" {
		t.Fatalf("joined as %s %v %v %v %q %q", role, perms, reportsTo, locs, name, staffID)
	}
	// Used once.
	w = doJSON(t, h.AcceptInviteLink, http.MethodPost, "/invites/x/accept", nil, nil, map[string]string{}, map[string]string{"token": token})
	if w.Code != http.StatusGone {
		t.Fatalf("second accept: %d", w.Code)
	}

	// Revoked links stop working.
	_, v2 := invite(owner, map[string]any{"email": "ann-" + randHex(4) + "@example.com", "role": "viewer"})
	w = doJSON(t, h.RevokeInvite, http.MethodDelete, "/orgs/invites/x", owner, nil, nil, map[string]string{"id": v2.ID})
	if w.Code != http.StatusNoContent {
		t.Fatalf("revoke: %d %s", w.Code, w.Body.String())
	}
	w = doJSON(t, h.AcceptInviteLink, http.MethodPost, "/invites/x/accept", nil, nil, map[string]string{}, map[string]string{"token": tokenOf(v2.Link)})
	if w.Code != http.StatusGone {
		t.Fatalf("accept a revoked invite: %d", w.Code)
	}

	// A branch manager: team leaders and staff, their own locations, no hr.
	bossEmail := "bea-" + randHex(4) + "@example.com"
	bossID, err := h.joinOrg(ctx, bossEmail, "Bea", orgID, "branch_manager")
	if err != nil {
		t.Fatal(err)
	}
	boss := &Claims{OrgID: orgID, Role: "branch_manager", Email: bossEmail, Locs: []string{mainLoc}}
	boss.Subject = bossID
	for _, c := range []struct {
		body map[string]any
		want int
	}{
		{map[string]any{"email": "x1-" + randHex(4) + "@e.com", "role": "admin", "locations": []string{mainLoc}}, 403},
		{map[string]any{"email": "x2-" + randHex(4) + "@e.com", "role": "member", "locations": []string{westLoc}}, 403},
		{map[string]any{"email": "x3-" + randHex(4) + "@e.com", "role": "member", "perms": []string{"hr"}, "locations": []string{mainLoc}}, 403},
		{map[string]any{"email": "x4-" + randHex(4) + "@e.com", "role": "member"}, 400},
		{map[string]any{"email": email, "role": "member", "locations": []string{mainLoc}}, 409}, // already has an account
	} {
		if code, _ := invite(boss, c.body); code != c.want {
			t.Errorf("manager invite %v: %d, want %d", c.body, code, c.want)
		}
	}
	code, v3 := invite(boss, map[string]any{"email": "tom-" + randHex(4) + "@e.com", "role": "team_leader", "perms": []string{"warehouse"}, "locations": []string{mainLoc}})
	if code != http.StatusCreated || v3.ReportsTo == nil || *v3.ReportsTo != bossID {
		t.Fatalf("manager invites a team leader (reports to them by default): %d %+v", code, v3)
	}
	// A manager lists only their own invites, and can't revoke the owner's.
	w = doJSON(t, h.ListInvites, http.MethodGet, "/orgs/invites", boss, nil, nil, nil)
	var mine []inviteView
	json.Unmarshal(w.Body.Bytes(), &mine)
	if len(mine) != 1 || mine[0].ID != v3.ID {
		t.Fatalf("manager's invites: %+v", mine)
	}
	_, v4 := invite(owner, map[string]any{"email": "zed-" + randHex(4) + "@example.com", "role": "member"})
	w = doJSON(t, h.RevokeInvite, http.MethodDelete, "/orgs/invites/x", boss, nil, nil, map[string]string{"id": v4.ID})
	if w.Code != http.StatusNotFound {
		t.Fatalf("manager revoking the owner's invite: %d", w.Code)
	}
	// Staff can't invite.
	staff := &Claims{OrgID: orgID, Role: "member"}
	if code, _ := invite(staff, map[string]any{"email": "q-" + randHex(4) + "@e.com", "role": "member"}); code != http.StatusForbidden {
		t.Fatalf("staff invite: %d", code)
	}
}
