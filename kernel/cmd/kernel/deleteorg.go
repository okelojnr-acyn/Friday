package main

// `kernel delete-org <org id> --yes`: removes one business and everything
// it owns from this Friday (roadmap item 9). Friday Host runs it on the
// shared Friday when a Friday Cloud account's 14-day deletion hold ends;
// a final export was taken at the start of the hold.
//
// Every table with an org_id column loses that business's rows, in one
// transaction with app.current_org_id set (row-level security still
// limits each DELETE to this business). Tables are emptied in passes:
// one blocked by a foreign key is retried after the others, and if a pass
// makes no progress nothing is deleted at all. People's logins stay (they
// may belong to other businesses); their memberships here go.

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
)

var orgIDRe = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

func runDeleteOrg(args []string) error {
	if len(args) != 2 || args[1] != "--yes" {
		return errors.New("usage: kernel delete-org <org id> --yes (removes the business and all its data)")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	n, err := deleteOrg(ctx, pool, args[0])
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "%s: deleted (%d rows)\n", args[0], n)
	return nil
}

func quoteIdent(s string) string { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }

func deleteOrg(ctx context.Context, pool *pgxpool.Pool, orgID string) (int64, error) {
	if !orgIDRe.MatchString(orgID) {
		return 0, fmt.Errorf("org id %q isn't a uuid", orgID)
	}
	tx, err := pool.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx)
	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core.orgs WHERE id::text = $1)`, orgID).Scan(&exists); err != nil {
		return 0, err
	}
	if !exists {
		return 0, fmt.Errorf("no organisation %s", orgID)
	}
	if _, err := tx.Exec(ctx, `SELECT set_config('app.current_org_id', $1, true)`, orgID); err != nil {
		return 0, err
	}
	rows, err := tx.Query(ctx, `
		SELECT c.table_schema, c.table_name FROM information_schema.columns c
		JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
		WHERE c.column_name = 'org_id' AND t.table_type = 'BASE TABLE'
		  AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
		ORDER BY c.table_schema, c.table_name`)
	if err != nil {
		return 0, err
	}
	var left [][2]string
	for rows.Next() {
		var s, t string
		if err := rows.Scan(&s, &t); err != nil {
			rows.Close()
			return 0, err
		}
		left = append(left, [2]string{s, t})
	}
	rows.Close()

	var total int64
	for len(left) > 0 {
		var blocked [][2]string
		var lastErr error
		for _, st := range left {
			n, err := deleteRows(ctx, tx, orgID, st[0], st[1])
			if err != nil {
				blocked, lastErr = append(blocked, st), err
				continue
			}
			total += n
		}
		if len(blocked) == len(left) {
			return 0, fmt.Errorf("%s.%s won't empty: %w", blocked[0][0], blocked[0][1], lastErr)
		}
		left = blocked
	}
	tag, err := tx.Exec(ctx, `DELETE FROM core.orgs WHERE id::text = $1`, orgID)
	if err != nil {
		return 0, err
	}
	total += tag.RowsAffected()
	return total, tx.Commit(ctx)
}

// deleteRows empties one table of the org's rows behind a savepoint, so a
// foreign key that blocks it leaves the transaction usable for a retry.
func deleteRows(ctx context.Context, tx pgx.Tx, orgID, schema, table string) (int64, error) {
	sp, err := tx.Begin(ctx)
	if err != nil {
		return 0, err
	}
	tag, err := sp.Exec(ctx, fmt.Sprintf(`DELETE FROM %s.%s WHERE org_id::text = $1`, quoteIdent(schema), quoteIdent(table)), orgID)
	if err != nil {
		sp.Rollback(ctx)
		return 0, err
	}
	return tag.RowsAffected(), sp.Commit(ctx)
}
