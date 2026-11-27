package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
)

func newKey(t *testing.T) *sealed.Box {
	b := make([]byte, 32)
	rand.Read(b)
	box, err := sealed.New(base64.StdEncoding.EncodeToString(b))
	if err != nil {
		t.Fatal(err)
	}
	return box
}

// Roadmap item 10: a business moved out and back in comes back whole:
// the business, its people, and its connected services' keys, sealed with
// the new Friday's own key (never in the clear in the bundle).
func TestMoveOutAndInRoundTrip(t *testing.T) {
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
	email := fmt.Sprintf("m%d@x.test", time.Now().UnixNano())
	orgID, _, err := bootstrap(ctx, pool, "Moving Shop", email, "")
	if err != nil {
		t.Fatal(err)
	}
	oldKey, moveKey, newOwn := newKey(t), newKey(t), newKey(t)
	cfg, _ := oldKey.Seal([]byte(`{"secret_key":"sk_live_abc"}`))
	if _, err := pool.Exec(ctx, `INSERT INTO core.integration_credentials (org_id, provider, config) VALUES ($1, 'paystack', $2)`, orgID, cfg); err != nil {
		t.Fatal(err)
	}

	var bundle bytes.Buffer
	if err := moveOut(ctx, pool, orgID, oldKey, moveKey, "test", &bundle); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(bundle.Bytes(), []byte("sk_live_abc")) {
		t.Fatal("a key is in the clear in the bundle")
	}

	// The business is still here: refused (the command also refuses any
	// other business; this shared test database has others).
	if _, _, err := moveIn(ctx, pool, bundle.Bytes(), moveKey, newOwn, false); err == nil {
		t.Fatal("move-in onto a Friday that has the business must refuse")
	}
	if _, err := deleteOrg(ctx, pool, orgID); err != nil {
		t.Fatal(err)
	}

	got, n, err := moveIn(ctx, pool, bundle.Bytes(), moveKey, newOwn, false)
	if err != nil {
		t.Fatal(err)
	}
	if got != orgID || n < 2 {
		t.Fatalf("moved in %s with %d rows", got, n)
	}
	var role string
	if err := pool.QueryRow(ctx, `SELECT m.role FROM core.memberships m JOIN core.users u ON u.id = m.user_id WHERE m.org_id::text = $1 AND u.email = $2`, orgID, email).Scan(&role); err != nil || role != "owner" {
		t.Fatalf("owner not moved: %q %v", role, err)
	}
	var stored []byte
	if err := pool.QueryRow(ctx, `SELECT config FROM core.integration_credentials WHERE org_id::text = $1 AND provider = 'paystack'`, orgID).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	plain, err := newOwn.Open(stored)
	if err != nil || !bytes.Contains(plain, []byte("sk_live_abc")) {
		t.Fatalf("the key didn't move under the new Friday's key: %s %v", plain, err)
	}
}
