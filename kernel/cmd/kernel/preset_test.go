package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/auth"
	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

func TestSpendingForSize(t *testing.T) {
	for _, c := range []struct {
		stores, staff int
		want          string
	}{{1, 3, "simple"}, {1, 6, "standard"}, {3, 49, "standard"}, {4, 5, "strict"}, {1, 50, "strict"}} {
		if got := spendingFor(c.stores, c.staff); got != c.want {
			t.Fatalf("%d stores %d staff: %s, want %s", c.stores, c.staff, got, c.want)
		}
	}
	for trade, apps := range tradeApps {
		for _, a := range apps {
			if a == "web3" {
				t.Fatalf("%s starts with web3", trade)
			}
		}
	}
}

// A new business from onboarding: a wholesaler in Uganda with 3 stores.
func TestPresetShapesANewBusiness(t *testing.T) {
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
	if err := (&org.Catalog{Pool: pool, Apps: registry.Load()}).SeedApps(ctx); err != nil {
		t.Fatal(err)
	}
	orgID, _, err := bootstrap(ctx, pool, "Okumu Wholesale", fmt.Sprintf("o%d@x.test", time.Now().UnixNano()), "")
	if err != nil {
		t.Fatal(err)
	}
	if err := preset(ctx, pool, orgID, "wholesale", "UG", 3, 12); err != nil {
		t.Fatal(err)
	}
	var currency, zone string
	var vat int
	var policy []byte
	if err := pool.QueryRow(ctx, `SELECT currency, tax_rate_bp, time_zone, spending_policy FROM core.orgs WHERE id::text = $1`, orgID).
		Scan(&currency, &vat, &zone, &policy); err != nil {
		t.Fatal(err)
	}
	var p org.SpendingPolicy
	_ = json.Unmarshal(policy, &p)
	if currency != "UGX" || vat != 1800 || zone != "Africa/Kampala" || p.Preset != "standard" || p.AskFirstMember == 0 {
		t.Fatalf("settings: %s %d %s %+v", currency, vat, zone, p)
	}
	rows, _ := pool.Query(ctx, `SELECT app_name FROM core.app_installs WHERE org_id::text = $1`, orgID)
	var apps []string
	for rows.Next() {
		var a string
		rows.Scan(&a)
		apps = append(apps, a)
	}
	rows.Close()
	sort.Strings(apps)
	if fmt.Sprint(apps) != "[accounting crm fleets inventory invoicing minions]" {
		t.Fatalf("apps: %v", apps)
	}
	var stores int
	pool.QueryRow(ctx, `SELECT count(*) FROM core.locations WHERE org_id::text = $1`, orgID).Scan(&stores)
	if stores != 3 {
		t.Fatalf("stores: %d", stores)
	}
	if err := preset(ctx, pool, orgID, "casino", "UG", 1, 1); err == nil {
		t.Fatal("an unknown trade was accepted")
	}
}

// MAX_ORGS keeps a customer's own Friday to one business: no new org
// past the cap, while its existing owner still gets their org back.
func TestBootstrapRespectsOrgCap(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set in CI")
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
	owner := fmt.Sprintf("cap%d@x.test", time.Now().UnixNano())
	first, _, err := bootstrap(ctx, pool, "Cap Shop", owner, "")
	if err != nil {
		t.Fatal(err)
	}
	var n int
	pool.QueryRow(ctx, `SELECT count(*) FROM core.orgs`).Scan(&n)
	t.Setenv("MAX_ORGS", fmt.Sprint(n))
	if _, _, err := bootstrap(ctx, pool, "Second Shop", "other"+owner, ""); !errors.Is(err, db.ErrOrgCap) {
		t.Fatalf("second business past the cap: %v", err)
	}
	if again, created, err := bootstrap(ctx, pool, "Cap Shop", owner, ""); err != nil || created || again != first {
		t.Fatalf("existing owner: %s %v %v", again, created, err)
	}
	t.Setenv("MAX_ORGS", fmt.Sprint(n+1000)) // other tests add orgs meanwhile
	if _, created, err := bootstrap(ctx, pool, "Second Shop", "other"+owner, ""); err != nil || !created {
		t.Fatalf("under the cap: %v %v", created, err)
	}
}

// `kernel suspend` blocks a business (the auth middleware's check) and
// lifting it clears the mark; an unknown org is an error.
func TestSuspendABusiness(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set in CI")
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
	orgID, _, err := bootstrap(ctx, pool, "Lapsed Shop", fmt.Sprintf("lapsed%d@x.test", time.Now().UnixNano()), "")
	if err != nil {
		t.Fatal(err)
	}
	if err := suspend(ctx, pool, orgID, true); err != nil {
		t.Fatal(err)
	}
	if !(&auth.Sessions{Pool: pool}).OrgSuspended(ctx, orgID) {
		t.Fatal("suspended business not seen as suspended")
	}
	if err := suspend(ctx, pool, orgID, false); err != nil {
		t.Fatal(err)
	}
	var on bool
	pool.QueryRow(ctx, `SELECT suspended_at IS NOT NULL FROM core.orgs WHERE id = $1`, orgID).Scan(&on)
	if on {
		t.Fatal("still suspended after off")
	}
	if err := suspend(ctx, pool, "00000000-0000-0000-0000-000000000000", true); err == nil {
		t.Fatal("unknown org suspended")
	}
}
