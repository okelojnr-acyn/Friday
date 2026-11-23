package integrations

import (
	"context"
	"encoding/base64"
	"os"
	"strings"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
)

// Keys stored before FRIDAY_SECRETS_KEY existed are sealed at startup and
// still read back the same.
func TestSealAllEncryptsPlainConfigs(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, "../../migrations"); err != nil {
		t.Fatal(err)
	}
	var org string
	if err := pool.QueryRow(ctx, `INSERT INTO core.orgs (name, slug) VALUES ('Seal Shop', 'seal-' || gen_random_uuid()) RETURNING id::text`).Scan(&org); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO core.integration_credentials (org_id, provider, config) VALUES ($1, 'paystack', '{"secret_key":"sk_live_abcd1234"}')`, org); err != nil {
		t.Fatal(err)
	}
	box, _ := sealed.New(base64.StdEncoding.EncodeToString([]byte(strings.Repeat("k", 32))))
	if _, err := SealAll(ctx, pool, box); err != nil {
		t.Fatal(err)
	}
	var stored []byte
	pool.QueryRow(ctx, `SELECT config FROM core.integration_credentials WHERE org_id = $1`, org).Scan(&stored)
	if strings.Contains(string(stored), "sk_live") || !sealed.IsSealed(stored) {
		t.Fatalf("still plain: %s", stored)
	}
	cfg, err := (&Handlers{Box: box}).decode(stored)
	if err != nil || cfg["secret_key"] != "sk_live_abcd1234" {
		t.Fatalf("read back: %v %v", cfg, err)
	}
}
