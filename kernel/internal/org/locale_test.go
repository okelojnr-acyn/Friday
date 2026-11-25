package org

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
)

func TestTimeZonesAndTheirCurrency(t *testing.T) {
	for tz, ok := range map[string]bool{"Africa/Nairobi": true, "America/New_York": true, "UTC": true, "Mars/Base": false, "": false, "Local": false} {
		if validTimeZone(tz) != ok {
			t.Errorf("%q valid=%v", tz, !ok)
		}
	}
	if CurrencyForZone("Africa/Kampala") != "UGX" || CurrencyForZone("America/Chicago") != "USD" || CurrencyForZone("Asia/Tokyo") != "" {
		t.Error("currency for zone")
	}
}

// The first owner's browser sets a new business's zone and currency; it
// never overwrites a zone already set, and staff only set their own.
func TestFirstSignInSetsTheBusinessZone(t *testing.T) {
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
	var orgID, owner, staff string
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Duka', 'duka-' || gen_random_uuid()) RETURNING id::text`).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	for _, x := range []struct {
		id   *string
		role string
	}{{&owner, "owner"}, {&staff, "member"}} {
		if err := pool.QueryRow(ctx, `INSERT INTO core.users (email) VALUES (gen_random_uuid() || '@x.test') RETURNING id::text`).Scan(x.id); err != nil {
			t.Fatal(err)
		}
		if _, err := pool.Exec(ctx, `INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, $3)`, orgID, *x.id, x.role); err != nil {
			t.Fatal(err)
		}
	}
	p := &People{Pool: pool}
	set := func(user, role, tz string) int {
		req := httptest.NewRequest("PUT", "/auth/me/time-zone", bytes.NewBufferString(`{"time_zone":"`+tz+`"}`))
		req = req.WithContext(auth.WithClaims(ctx, &auth.Claims{OrgID: orgID, Role: role, RegisteredClaims: jwt.RegisteredClaims{Subject: user}}))
		rec := httptest.NewRecorder()
		p.SetMyTimeZone(rec, req)
		return rec.Code
	}
	org := func() (tz, cur string) {
		_ = pool.QueryRow(ctx, `SELECT time_zone, currency FROM core.orgs WHERE id::text = $1`, orgID).Scan(&tz, &cur)
		return
	}
	if set(staff, "member", "Africa/Kampala") != http.StatusOK {
		t.Fatal("staff set their own")
	}
	if tz, _ := org(); tz != "" {
		t.Fatalf("staff set the business zone: %q", tz)
	}
	if set(owner, "owner", "Mars/Base") != http.StatusBadRequest {
		t.Fatal("unknown zone accepted")
	}
	if set(owner, "owner", "Africa/Kampala") != http.StatusOK {
		t.Fatal("owner set")
	}
	if tz, cur := org(); tz != "Africa/Kampala" || cur != "UGX" {
		t.Fatalf("new business: %q %q", tz, cur)
	}
	set(owner, "owner", "Europe/London") // travelling: theirs changes, the business's doesn't
	if tz, cur := org(); tz != "Africa/Kampala" || cur != "UGX" {
		t.Fatalf("zone overwritten: %q %q", tz, cur)
	}
	var mine string
	_ = pool.QueryRow(ctx, `SELECT time_zone FROM core.users WHERE id::text = $1`, owner).Scan(&mine)
	if mine != "Europe/London" {
		t.Fatalf("owner's own zone: %q", mine)
	}
}
