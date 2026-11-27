package main

// `kernel suspend <org id> on|off`: Friday Host suspends a business on its
// shared Friday when its subscription lapses, and lifts it once paid.
// Members are refused until then (auth.RequireAuth); nothing is deleted.

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
)

func runSuspend(args []string) error {
	if len(args) != 2 || (args[1] != "on" && args[1] != "off") {
		return errors.New("usage: kernel suspend <org id> on|off")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	if err := suspend(ctx, pool, args[0], args[1] == "on"); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "%s: suspended %s\n", args[0], args[1])
	return nil
}

func suspend(ctx context.Context, pool *pgxpool.Pool, orgID string, on bool) error {
	tag, err := pool.Exec(ctx, `UPDATE core.orgs SET suspended_at = CASE WHEN $2 THEN COALESCE(suspended_at, now()) END WHERE id::text = $1`, orgID, on)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return fmt.Errorf("no organisation %s", orgID)
	}
	return nil
}
