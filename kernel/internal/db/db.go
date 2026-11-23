// Package db provides the kernel's Postgres connection pool and a tiny
// migration runner. The kernel owns the "core" schema (orgs, users,
// memberships, app registry); each app service owns its own schema and
// migrates independently -- see apps/*/migrations.
package db

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func Connect(ctx context.Context, databaseURL string) (*pgxpool.Pool, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("ping: %w", err)
	}
	return pool, nil
}

// Migrate applies every .sql file in dir, in filename order, tracked in a
// core.schema_migrations table so re-running is a no-op. Deliberately not
// a migration framework dependency: a handful of numbered SQL files is all
// a project this size needs, and it's trivially readable by anyone.
func Migrate(ctx context.Context, pool *pgxpool.Pool, dir string) error {
	// One migrator at a time (two kernels starting together, or test
	// packages sharing a database), with a lock held by each migration's
	// own transaction. A session lock leaked behind PgBouncer's transaction
	// pooling (the unlock ran on another server connection), and the next
	// kernel waited on it until the role's statement timeout killed it.
	if err := locked(ctx, pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
			CREATE SCHEMA IF NOT EXISTS core;
			CREATE TABLE IF NOT EXISTS core.schema_migrations (
				filename TEXT PRIMARY KEY,
				applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
			);`)
		return err
	}); err != nil {
		return fmt.Errorf("bootstrap migrations table: %w", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		return fmt.Errorf("read migrations dir: %w", err)
	}

	var files []string
	for _, e := range entries {
		if !e.IsDir() && filepath.Ext(e.Name()) == ".sql" {
			files = append(files, e.Name())
		}
	}
	sort.Strings(files)

	for _, name := range files {
		sqlBytes, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return fmt.Errorf("read migration %s: %w", name, err)
		}
		if err := locked(ctx, pool, func(tx pgx.Tx) error {
			// Checked under the lock: another kernel may have just applied it.
			var already bool
			if err := tx.QueryRow(ctx,
				`SELECT EXISTS(SELECT 1 FROM core.schema_migrations WHERE filename = $1)`, name,
			).Scan(&already); err != nil || already {
				return err
			}
			if _, err := tx.Exec(ctx, string(sqlBytes)); err != nil {
				return err
			}
			_, err := tx.Exec(ctx, `INSERT INTO core.schema_migrations (filename) VALUES ($1)`, name)
			return err
		}); err != nil {
			return fmt.Errorf("apply %s: %w", name, err)
		}
	}
	return nil
}

// locked runs fn in a transaction holding the migrations lock, with no
// statement timeout (Friday Host gives tenant roles one; a migration on a
// big table may need longer, and must never stop halfway).
func locked(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `SET LOCAL statement_timeout = 0`); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(7302190411)`); err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
