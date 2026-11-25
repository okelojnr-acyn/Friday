package inbox

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

func TestComposeAndMoney(t *testing.T) {
	if Money(150000, "kes") != "KES 1,500" || Money(123456789, "USD") != "USD 1,234,567.89" {
		t.Error("money")
	}
	m, ok := Compose("minions.expense_claim.decided",
		Notice{Status: "rejected", DecidedByName: "Tom", Note: "photo is blurry", AmountCents: 1000, Currency: "KES", Description: "taxi"}, nil)
	if !ok || m.Title != "Tom rejected your claim" || !strings.Contains(m.Body, "taxi (KES 10): photo is blurry") {
		t.Errorf("rejected: %+v", m)
	}
	if m, _ := Compose("minions.expense_claim.paid", Notice{Method: "mpesa", AmountCents: 1000, Currency: "KES", Description: "taxi"}, nil); !strings.HasSuffix(m.Body, "by M-Pesa.") {
		t.Errorf("paid: %+v", m)
	}
	if m, _ := Compose("projects.task.overdue", Notice{Level: 2, Task: "Count shelf 4", AssigneeName: "Sam"}, nil); m.Title != "A task in your team is 3 days overdue" || m.Body != "Count shelf 4, given to Sam" {
		t.Errorf("overdue level 2: %+v", m)
	}
	if m, _ := Compose("projects.task.assigned", Notice{FromName: "Tom", Task: "Count shelf 4"}, nil); m.Title != "Tom gave you a task" || m.Path("member") != "/minions/" {
		t.Errorf("assigned: %+v", m)
	}
	if m, _ := Compose("minions.meeting.invited", Notice{FromName: "Bea", Meeting: "Stock count", StartsAt: "2026-11-27T07:00:00Z"}, Zone("Africa/Nairobi")); m.Title != "Bea invited you to a meeting" || m.Body != "Stock count, Fri 27 Nov, 10:00" || m.Path("member") != "/minions/calendar" {
		t.Errorf("meeting invite: %+v", m)
	}
	if _, ok := Compose("crm.opportunity.won", Notice{}, nil); ok {
		t.Error("other events say nothing")
	}
	needed, _ := Compose("minions.approval.needed", Notice{FromName: "Sam"}, nil)
	if needed.Path("member") != "/minions/team" || needed.Path("owner") != "/people/expense_claim" {
		t.Error("staff go to Minions, owners to Friday")
	}
}

// An event lands once per person (even delivered twice), with the link for
// their role; each person sees only their own; read marks them.
func TestInboxDeliverListRead(t *testing.T) {
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
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	person := func(role string) string {
		var id string
		if err := pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES (gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(&id); err != nil {
			t.Fatal(err)
		}
		if _, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, $3)`, orgID, id, role); err != nil {
			t.Fatal(err)
		}
		return id
	}
	lead, owner, other := person("team_leader"), person("owner"), person("member")
	in := &Inbox{Pool: pool}
	payload, _ := json.Marshal(Notice{ToUserIDs: []string{lead, owner}, FromName: "Sam", AmountCents: 150000, Currency: "KES", Description: "taxi"})
	for range 2 { // a retried delivery
		if err := in.Deliver(ctx, "ev-1", orgID, "minions.approval.needed", payload); err != nil {
			t.Fatal(err)
		}
	}
	list := func(user string) (out struct {
		Unread int    `json:"unread"`
		Items  []item `json:"items"`
	}) {
		req := httptest.NewRequest("GET", "/me/notifications", nil).WithContext(
			auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, RegisteredClaims: jwt.RegisteredClaims{Subject: user}}))
		rec := httptest.NewRecorder()
		in.List(rec, req)
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
			t.Fatal(rec.Body.String())
		}
		return
	}
	l := list(lead)
	if l.Unread != 1 || len(l.Items) != 1 || l.Items[0].Link != "/minions/team" || l.Items[0].Title != "Sam asks you to approve a claim" {
		t.Fatalf("lead: %+v", l)
	}
	if o := list(owner); len(o.Items) != 1 || o.Items[0].Link != "/people/expense_claim" {
		t.Fatalf("owner: %+v", o)
	}
	if x := list(other); len(x.Items) != 0 {
		t.Fatalf("someone else sees it: %+v", x)
	}

	read := func(user, body string) int {
		req := httptest.NewRequest("POST", "/me/notifications/read", bytes.NewBufferString(body)).WithContext(
			auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, RegisteredClaims: jwt.RegisteredClaims{Subject: user}}))
		rec := httptest.NewRecorder()
		in.Read(rec, req)
		return rec.Code
	}
	if read(other, `{"all": true}`) != http.StatusNoContent || list(lead).Unread != 1 {
		t.Fatal("someone else's read-all touched the lead's")
	}
	if read(lead, `{}`) != http.StatusBadRequest {
		t.Fatal("empty read accepted")
	}
	if read(lead, `{"ids": [`+jsonInt(l.Items[0].ID)+`]}`) != http.StatusNoContent || list(lead).Unread != 0 {
		t.Fatal("read")
	}
}

func jsonInt(n int64) string { b, _ := json.Marshal(n); return string(b) }
