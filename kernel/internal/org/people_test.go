package org

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/access"
	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// Plan section 12, step 1: staff IDs, locations, role/perms/locations/
// reports_to changes with their guards, and what a token carries.
func TestPeopleRolesLocationsAndTokens(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}

	var orgID string
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka Bora', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID))
	person := func(name, role string) string {
		var id string
		must(pool.QueryRow(ctx, `INSERT INTO core.users (email, full_name) VALUES ($1 || gen_random_uuid() || '@x.test', $1) RETURNING id::text`, name).Scan(&id))
		_, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, $3)`, orgID, id, role)
		must(err)
		return id
	}
	owner, admin, boss, lead, cashier := person("Olive", "owner"), person("Ade", "admin"), person("Bea", "branch_manager"), person("Tom", "team_leader"), person("Sam", "member")

	// Staff IDs come from the database, in order, from the business's name.
	var ids []string
	rows, err := pool.Query(ctx, `SELECT staff_id FROM core.memberships WHERE org_id = $1 ORDER BY created_at, staff_id`, orgID)
	must(err)
	for rows.Next() {
		var s string
		must(rows.Scan(&s))
		ids = append(ids, s)
	}
	rows.Close()
	if len(ids) != 5 || ids[0] != "DUK-0001" || ids[4] != "DUK-0005" {
		t.Fatalf("staff ids: %v", ids)
	}

	// A new business starts with its "Main" location.
	var main string
	must(pool.QueryRow(ctx, `SELECT id::text FROM core.locations WHERE org_id = $1 AND name = 'Main'`, orgID).Scan(&main))

	p := &People{Pool: pool}
	as := func(userID, role string) func(method, path, body string) (int, string) {
		return func(method, path, body string) (int, string) {
			r := httptest.NewRequest(method, path, bytes.NewBufferString(body))
			r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: role, RegisteredClaims: jwt.RegisteredClaims{Subject: userID}}))
			w := httptest.NewRecorder()
			mux := http.NewServeMux()
			mux.HandleFunc("PATCH /orgs/members/{user_id}", p.UpdatePerson)
			mux.HandleFunc("POST /orgs/locations", p.SaveLocation)
			mux.HandleFunc("GET /orgs/locations", p.Locations)
			mux.ServeHTTP(w, r)
			return w.Code, w.Body.String()
		}
	}
	asOwner, asAdmin, asBoss := as(owner, "owner"), as(admin, "admin"), as(boss, "branch_manager")

	code, body := asOwner(http.MethodPost, "/orgs/locations", `{"name":"Westlands","kind":"store"}`)
	if code != 200 {
		t.Fatalf("add location: %d %s", code, body)
	}
	var west locationView
	json.Unmarshal([]byte(body), &west)
	if code, _ := asBoss(http.MethodPost, "/orgs/locations", `{"name":"Elsewhere"}`); code != http.StatusForbidden {
		t.Fatalf("a branch manager added a location: %d", code)
	}

	// Role, perms, locations and reports_to in one save.
	code, body = asOwner(http.MethodPatch, "/orgs/members/"+cashier,
		`{"perms":["cashier","cashier"],"locations":["`+west.ID+`"],"reports_to":"`+lead+`"}`)
	if code != http.StatusNoContent {
		t.Fatalf("update cashier: %d %s", code, body)
	}
	if code, _ := asOwner(http.MethodPatch, "/orgs/members/"+lead, `{"reports_to":"`+boss+`"}`); code != http.StatusNoContent {
		t.Fatalf("lead reports to boss: %d", code)
	}
	// Guards.
	for _, c := range []struct {
		who          func(string, string, string) (int, string)
		target, body string
		want         int
	}{
		{asOwner, cashier, `{"perms":["magic"]}`, 400},
		{asOwner, cashier, `{"role":"king"}`, 400},
		{asOwner, cashier, `{"locations":["00000000-0000-0000-0000-000000000000"]}`, 400},
		{asOwner, boss, `{"reports_to":"` + cashier + `"}`, 400}, // a loop: cashier -> lead -> boss
		{asOwner, cashier, `{"reports_to":"` + cashier + `"}`, 400},
		{asAdmin, cashier, `{"role":"owner"}`, 403},
		{asAdmin, owner, `{"perms":["hr"]}`, 403},
		{asOwner, owner, `{"role":"admin"}`, 400}, // the only owner
		{asBoss, cashier, `{"perms":["hr"]}`, 403},
	} {
		if code, body := c.who(http.MethodPatch, "/orgs/members/"+c.target, c.body); code != c.want {
			t.Errorf("%s: %d %s, want %d", c.body, code, body, c.want)
		}
	}

	// What a token carries.
	perms, locs, team, err := access.Load(ctx, pool, orgID, cashier, "member")
	must(err)
	if !slices.Equal(perms, []string{"cashier"}) || !slices.Equal(locs, []string{west.ID}) || team != nil {
		t.Fatalf("cashier scope: %v %v %v", perms, locs, team)
	}
	_, _, team, err = access.Load(ctx, pool, orgID, boss, "branch_manager")
	must(err)
	slices.Sort(team)
	want := []string{lead, cashier}
	slices.Sort(want)
	if !slices.Equal(team, want) {
		t.Fatalf("boss's team: %v, want %v", team, want)
	}
	perms, locs, _, err = access.Load(ctx, pool, orgID, admin, "admin")
	must(err)
	if len(perms) != len(access.Perms) || !slices.Equal(locs, []string{"*"}) {
		t.Fatalf("admin scope: %v %v", perms, locs)
	}
	_, locs, _, _ = access.Load(ctx, pool, orgID, lead, "team_leader")
	if !slices.Equal(locs, []string{"*"}) {
		t.Fatalf("no locations listed means all: %v", locs)
	}

	iss := auth.NewIssuer("test-secret", 0)
	iss.Scope = func(ctx context.Context, userID, orgID, role string) ([]string, []string, []string, error) {
		return access.Load(ctx, pool, orgID, userID, role)
	}
	tok, err := iss.Issue(cashier, orgID, "member", "sam@x.test")
	must(err)
	parts := strings.Split(tok, ".")
	payload, _ := jwt.NewParser().DecodeSegment(parts[1])
	if !strings.Contains(string(payload), `"perms":["cashier"]`) || !strings.Contains(string(payload), west.ID) {
		t.Fatalf("token doesn't carry the scope: %s", payload)
	}

	// Leaving clears whoever reported to them.
	m := &Members{Pool: pool}
	r := httptest.NewRequest(http.MethodDelete, "/orgs/members/"+lead, nil)
	r.SetPathValue("user_id", lead)
	r = r.WithContext(auth.WithClaims(r.Context(), &auth.Claims{OrgID: orgID, Role: "owner"}))
	w := httptest.NewRecorder()
	m.Remove(w, r)
	var reportsTo *string
	must(pool.QueryRow(ctx, `SELECT reports_to::text FROM core.memberships WHERE org_id = $1 AND user_id::text = $2`, orgID, cashier).Scan(&reportsTo))
	if w.Code != http.StatusNoContent || reportsTo != nil {
		t.Fatalf("remove lead: %d, cashier still reports to %v", w.Code, reportsTo)
	}
}
