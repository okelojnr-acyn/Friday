package main

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// Roadmap item 9: deleting one business on a shared Friday removes its
// rows everywhere and leaves its neighbour untouched.
func TestDeleteOrgRemovesOneBusinessOnly(t *testing.T) {
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
	stamp := time.Now().UnixNano()
	gone, _, err := bootstrap(ctx, pool, "Gone Shop", fmt.Sprintf("g%d@x.test", stamp), "")
	if err != nil {
		t.Fatal(err)
	}
	kept, _, err := bootstrap(ctx, pool, "Kept Shop", fmt.Sprintf("k%d@x.test", stamp), "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := deleteOrg(ctx, pool, gone); err != nil {
		t.Fatal(err)
	}
	count := func(orgID string) (n int) {
		pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM core.orgs WHERE id::text = $1) + (SELECT count(*) FROM core.memberships WHERE org_id::text = $1)`, orgID).Scan(&n)
		return
	}
	if n := count(gone); n != 0 {
		t.Fatalf("%d rows of the deleted business left", n)
	}
	if n := count(kept); n < 2 {
		t.Fatalf("the other business lost rows: %d", n)
	}
	if _, err := deleteOrg(ctx, pool, gone); err == nil {
		t.Fatal("deleting it again should say there's no such business")
	}
	if _, err := deleteOrg(ctx, pool, "not-a-uuid"); err == nil {
		t.Fatal("a bad id must be refused")
	}
}
