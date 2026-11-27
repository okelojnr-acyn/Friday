package main

// `kernel bootstrap "<org name>" <owner email> [full name]`: creates the
// first organisation and its owner on a fresh install, the same rows a
// sign-up makes (every app enabled), and prints the org's id on stdout.
// Idempotent: if that email already belongs to an org, it prints that
// org's id and changes nothing. Friday Host runs it after a customer
// server install to learn the install's kernel_org_id.

import (
	"context"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/org"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

var bootstrapSlug = regexp.MustCompile(`[^a-z0-9]+`)

func runBootstrap(args []string) error {
	if len(args) < 2 || strings.TrimSpace(args[0]) == "" || !strings.Contains(args[1], "@") {
		return errors.New(`usage: kernel bootstrap "<org name>" <owner email> [full name]`)
	}
	orgName, email := strings.TrimSpace(args[0]), strings.ToLower(strings.TrimSpace(args[1]))
	fullName := ""
	if len(args) > 2 {
		fullName = strings.TrimSpace(args[2])
	}

	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	if err := db.Migrate(ctx, pool, envOr("MIGRATIONS_DIR", "kernel/migrations")); err != nil {
		return fmt.Errorf("migrate: %w", err)
	}
	if err := (&org.Catalog{Pool: pool, Apps: registry.Load()}).SeedApps(ctx); err != nil {
		return fmt.Errorf("seed apps: %w", err)
	}

	orgID, created, err := bootstrap(ctx, pool, orgName, email, fullName)
	if err != nil {
		return err
	}
	if created {
		fmt.Fprintf(os.Stderr, "created %q with owner %s\n", orgName, email)
	} else {
		fmt.Fprintf(os.Stderr, "%s already has an organisation; nothing changed\n", email)
	}
	fmt.Println(orgID)
	return nil
}

func bootstrap(ctx context.Context, pool *pgxpool.Pool, orgName, email, fullName string) (string, bool, error) {
	var existing string
	err := pool.QueryRow(ctx, `
		SELECT m.org_id FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE lower(u.email) = $1 ORDER BY m.created_at LIMIT 1`, email).Scan(&existing)
	if err == nil {
		return existing, false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", false, err
	}

	tx, err := pool.Begin(ctx)
	if err != nil {
		return "", false, err
	}
	defer tx.Rollback(ctx)
	if err := db.CheckOrgCap(ctx, tx); err != nil {
		return "", false, err
	}

	base := strings.Trim(bootstrapSlug.ReplaceAllString(strings.ToLower(orgName), "-"), "-")
	if base == "" {
		base = "org"
	}
	var orgID string
	for i := 0; ; i++ {
		slug := base
		if i > 0 {
			slug = fmt.Sprintf("%s-%d", base, i+1)
		}
		err = tx.QueryRow(ctx,
			`INSERT INTO core.orgs (name, slug) VALUES ($1, $2) ON CONFLICT (slug) DO NOTHING RETURNING id`,
			orgName, slug).Scan(&orgID)
		if err == nil {
			break
		}
		if !errors.Is(err, pgx.ErrNoRows) || i > 50 {
			return "", false, fmt.Errorf("create org: %w", err)
		}
	}

	var userID string
	if err := tx.QueryRow(ctx,
		`INSERT INTO core.users (email, full_name) VALUES ($1, $2)
		 ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id`,
		email, fullName).Scan(&userID); err != nil {
		return "", false, fmt.Errorf("create owner: %w", err)
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO core.memberships (org_id, user_id, role) VALUES ($1, $2, 'owner')`, orgID, userID); err != nil {
		return "", false, fmt.Errorf("make owner: %w", err)
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO core.app_installs (org_id, app_name) SELECT $1, name FROM core.apps`, orgID); err != nil {
		return "", false, fmt.Errorf("enable apps: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", false, err
	}
	return orgID, true, nil
}
