package db

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// Two kernels starting at once apply a new migration exactly once, and a
// migrator never keeps a lock after it's done (it used to, behind
// PgBouncer's transaction pooling).
func TestConcurrentMigratorsApplyOnceAndLeaveNoLock(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	dir := t.TempDir()
	table := fmt.Sprintf("core.migrate_race_%d", time.Now().UnixNano())
	name := fmt.Sprintf("9999_race_%d.sql", time.Now().UnixNano())
	sql := "CREATE TABLE " + table + " (id int); INSERT INTO " + table + " VALUES (1);"
	if err := os.WriteFile(filepath.Join(dir, name), []byte(sql), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Exec(ctx, "DROP TABLE IF EXISTS "+table)
		pool.Exec(ctx, "DELETE FROM core.schema_migrations WHERE filename = $1", name)
	})

	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for range 2 {
		wg.Add(1)
		go func() { defer wg.Done(); errs <- Migrate(ctx, pool, dir) }()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	var rows int
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM "+table).Scan(&rows); err != nil || rows != 1 {
		t.Fatalf("applied %d times: %v", rows, err)
	}
	var held int
	pool.QueryRow(ctx, `SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 7302190411 % 4294967296`).Scan(&held)
	if held != 0 {
		t.Fatalf("migrations lock still held by %d session(s)", held)
	}
}
