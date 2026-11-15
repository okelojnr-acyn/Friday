package dbcheck

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/acyn-innovation/friday/kernel/internal/db"
)

func TestURLChecks(t *testing.T) {
	cases := map[string]string{
		"postgres://u:p@db.example.com:5432/shop?sslmode=require":  "ok",
		"postgresql://u:p@db.example.com/shop?sslmode=verify-full": "ok",
		"postgres://u:p@db.example.com/shop":                       "fail",
		"postgres://u:p@db.example.com/shop?sslmode=prefer":        "fail",
		"postgres://friday:p@postgres:5432/friday":                 "ok",
		"mysql://u:p@db.example.com/shop":                          "fail",
		"postgres://db.example.com/shop?sslmode=require":           "fail",
		"postgres://u:p@db.example.com/?sslmode=require":           "fail",
	}
	for raw, want := range cases {
		rs := URLChecks(raw)
		if rs[0].Level != want {
			t.Errorf("%s: want %s, got %s", raw, want, rs[0])
		}
		for _, r := range rs {
			if strings.Contains(r.Message, ":p@") {
				t.Errorf("message leaks the URL: %s", r)
			}
		}
	}
}

func TestCheckOnRealPostgres(t *testing.T) {
	url := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if url == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	fresh := []string{"dbcheck_fresh_a", "dbcheck_fresh_b"}
	if rs := Check(ctx, pool, url, fresh); Failed(rs) {
		t.Fatalf("an empty database should pass: %v", rs)
	}

	// Someone else's schema with the same name as one of Friday's.
	pool.Exec(ctx, `DROP SCHEMA IF EXISTS dbcheck_taken CASCADE`)
	if _, err := pool.Exec(ctx, `CREATE SCHEMA dbcheck_taken; CREATE TABLE dbcheck_taken.orders (id int)`); err != nil {
		t.Fatal(err)
	}
	defer pool.Exec(ctx, `DROP SCHEMA IF EXISTS dbcheck_taken CASCADE`)
	rs := Check(ctx, pool, url, []string{"dbcheck_taken"})
	if !Failed(rs) {
		t.Fatalf("a foreign schema with Friday's name must fail: %v", rs)
	}

	// Friday's own schema from an earlier run is fine.
	if _, err := pool.Exec(ctx, `CREATE TABLE dbcheck_taken.schema_migrations (filename text)`); err != nil {
		t.Fatal(err)
	}
	if rs := Check(ctx, pool, url, []string{"dbcheck_taken"}); Failed(rs) {
		t.Fatalf("Friday's own schema should pass: %v", rs)
	}
}
