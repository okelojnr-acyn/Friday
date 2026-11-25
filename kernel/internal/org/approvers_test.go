package org

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

// HR plan phase 1: a request walks up reports_to, nearest first; owners
// and admins are the top; limits are per business, owners and admins set them.
func TestApproversAndLimits(t *testing.T) {
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
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	var orgID string
	must(pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID))
	person := func(name, role, boss string) string {
		var id string
		must(pool.QueryRow(ctx, `INSERT INTO core.users (email, full_name) VALUES ($1 || gen_random_uuid() || '@x.test', $1) RETURNING id::text`, name).Scan(&id))
		var b any
		if boss != "" {
			b = boss
		}
		_, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role, reports_to) VALUES ($1, $2, $3, $4::uuid)`, orgID, id, role, b)
		must(err)
		return id
	}
	owner := person("Olive", "owner", "")
	admin := person("Ade", "admin", owner)
	boss := person("Bea", "branch_manager", admin)
	lead := person("Tom", "team_leader", boss)
	sam := person("Sam", "member", lead)

	p := &People{Pool: pool, InternalToken: "tok"}
	get := func(user string) (out struct {
		Limits ApprovalLimits `json:"limits"`
		Chain  []Approver     `json:"chain"`
		Top    []Approver     `json:"top"`
	}) {
		req := httptest.NewRequest("GET", "/internal/people/"+orgID+"/approvers/"+user, nil)
		req.SetPathValue("org_id", orgID)
		req.SetPathValue("user_id", user)
		req.Header.Set("Authorization", "Bearer tok")
		rec := httptest.NewRecorder()
		p.Approvers(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("approvers: %d %s", rec.Code, rec.Body)
		}
		must(json.Unmarshal(rec.Body.Bytes(), &out))
		return
	}
	got := get(sam)
	if len(got.Chain) != 4 || got.Chain[0].UserID != lead || got.Chain[1].UserID != boss || got.Chain[3].UserID != owner {
		t.Fatalf("chain nearest first: %+v", got.Chain)
	}
	if got.Chain[0].Name != "Tom" || got.Limits != DefaultApprovalLimits() {
		t.Fatalf("names and default limits: %+v %+v", got.Chain[0], got.Limits)
	}
	if len(got.Top) != 2 || got.Top[0].UserID != owner {
		t.Fatalf("top is owners then admins: %+v", got.Top)
	}
	if top := get(owner).Top; len(top) != 1 || top[0].UserID != admin {
		t.Fatalf("an owner's own request goes to the others: %+v", top)
	}

	put := func(role string, body string) int {
		req := httptest.NewRequest("PUT", "/orgs/approval-limits", bytes.NewBufferString(body))
		req = req.WithContext(auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, Role: role, RegisteredClaims: jwt.RegisteredClaims{Subject: owner}}))
		rec := httptest.NewRecorder()
		p.PutApprovalLimits(rec, req)
		return rec.Code
	}
	if code := put("branch_manager", `{"team_leader":1,"branch_manager":2}`); code != http.StatusForbidden {
		t.Fatalf("a manager set limits: %d", code)
	}
	if code := put("owner", `{"team_leader":-1,"branch_manager":2}`); code != http.StatusBadRequest {
		t.Fatalf("negative limit: %d", code)
	}
	if code := put("owner", `{"team_leader":500000,"branch_manager":5000000}`); code != http.StatusOK {
		t.Fatalf("owner set limits: %d", code)
	}
	if l := get(sam).Limits; l.TeamLeader != 500000 || l.BranchManager != 5000000 {
		t.Fatalf("limits saved: %+v", l)
	}

	// Person: a member by id or email; a stranger is 404.
	lookup := func(q string) (int, Approver) {
		req := httptest.NewRequest("GET", "/internal/people/"+orgID+"/person?"+q, nil)
		req.SetPathValue("org_id", orgID)
		req.Header.Set("Authorization", "Bearer tok")
		rec := httptest.NewRecorder()
		p.Person(rec, req)
		var a Approver
		json.Unmarshal(rec.Body.Bytes(), &a)
		return rec.Code, a
	}
	if code, a := lookup("user_id=" + lead); code != http.StatusOK || a.Name != "Tom" || a.Role != "team_leader" {
		t.Fatalf("person by id: %d %+v", code, a)
	}
	var email string
	must(pool.QueryRow(ctx, `SELECT email FROM core.users WHERE id::text = $1`, sam).Scan(&email))
	if code, a := lookup("email=" + strings.ToUpper(email)); code != http.StatusOK || a.UserID != sam {
		t.Fatalf("person by email: %d %+v", code, a)
	}
	if code, _ := lookup("email=nobody@x.test"); code != http.StatusNotFound {
		t.Fatalf("a stranger: %d", code)
	}
}
