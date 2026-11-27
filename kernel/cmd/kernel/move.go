package main

// Moving a business from the shared Friday (Friday Cloud) to its own
// server (roadmap item 10):
//
//	kernel move-out <org id>   (stdin: the move key)          > bundle.zip
//	kernel move-in             (stdin: the move key, then the bundle)
//
// The bundle is the business row, its people (their logins, not their
// passkeys), and every row it owns in every schema, as JSON. Connected
// services' keys are opened with this Friday's FRIDAY_SECRETS_KEY and
// sealed again with the one-time move key, so they're never in the clear;
// move-in opens them with the move key and seals them with its own.
//
// Left behind on purpose: passkeys (they belong to the old address;
// people sign in by email code once and add a new one), sign-in codes and
// sessions, push subscriptions (each Friday has its own push keys), and
// the event outboxes (re-sending them would book sales twice).
//
// move-in runs on a Friday with no business on it (Friday Host deletes
// the one setup made first), in one transaction: all or nothing.

import (
	"archive/zip"
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/sealed"
)

// Tables with an org_id that stay behind (see the package comment).
var moveSkip = map[string]bool{
	"core.webauthn_credentials": true,
	"core.webauthn_challenges":  true,
	"core.otp_codes":            true,
	"core.guss_link_codes":      true,
	"core.guss_web_codes":       true,
	"core.step_ups":             true,
	"core.sessions":             true,
	"core.push_subscriptions":   true,
	"core.event_deliveries":     true,
}

func moveSkipped(schema, table string) bool {
	return moveSkip[schema+"."+table] || table == "event_outbox" ||
		schema == "pg_catalog" || schema == "information_schema" || strings.HasPrefix(schema, "pg_")
}

type moveTable struct {
	Schema string `json:"schema"`
	Table  string `json:"table"`
	Rows   int    `json:"rows"`
}

type moveManifest struct {
	OrgID   string      `json:"org_id"`
	Version string      `json:"friday_version"`
	At      time.Time   `json:"at"`
	Tables  []moveTable `json:"tables"`
}

// readMoveKey takes the first line of stdin: the one-time move key.
func readMoveKey(r *bufio.Reader) (*sealed.Box, error) {
	line, err := r.ReadString('\n')
	if err != nil && line == "" {
		return nil, errors.New("the move key must come first on stdin")
	}
	box, err := sealed.New(strings.TrimSpace(line))
	if err != nil || box == nil {
		return nil, errors.New("the move key must be 32 bytes, base64")
	}
	return box, nil
}

func runMoveOut(args []string) error {
	if len(args) != 1 {
		return errors.New("usage: kernel move-out <org id> (the move key on stdin) > bundle.zip")
	}
	in := bufio.NewReader(os.Stdin)
	moveKey, err := readMoveKey(in)
	if err != nil {
		return err
	}
	own, err := sealed.New(os.Getenv("FRIDAY_SECRETS_KEY"))
	if err != nil {
		return err
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	return moveOut(ctx, pool, args[0], own, moveKey, os.Getenv("FRIDAY_VERSION"), os.Stdout)
}

func runMoveIn(args []string) error {
	if len(args) != 0 {
		return errors.New("usage: kernel move-in (the move key, then the bundle, on stdin)")
	}
	in := bufio.NewReader(os.Stdin)
	moveKey, err := readMoveKey(in)
	if err != nil {
		return err
	}
	own, err := sealed.New(os.Getenv("FRIDAY_SECRETS_KEY"))
	if err != nil {
		return err
	}
	// shortcut: the bundle is read into memory (zip needs random access);
	// stream it to a temp file if a business outgrows the server's memory.
	bundle, err := io.ReadAll(in)
	if err != nil {
		return err
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	orgID, n, err := moveIn(ctx, pool, bundle, moveKey, own, true)
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "moved in %s (%d rows)\n", orgID, n)
	fmt.Println(orgID)
	return nil
}

// orgTables lists every base table with an org_id that moves.
func orgTables(ctx context.Context, q interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
}) ([][2]string, error) {
	rows, err := q.Query(ctx, `
		SELECT c.table_schema, c.table_name FROM information_schema.columns c
		JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
		WHERE c.column_name = 'org_id' AND t.table_type = 'BASE TABLE'
		ORDER BY c.table_schema, c.table_name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out [][2]string
	for rows.Next() {
		var s, t string
		if err := rows.Scan(&s, &t); err != nil {
			return nil, err
		}
		if !moveSkipped(s, t) && !(s == "core" && t == "orgs") {
			out = append(out, [2]string{s, t})
		}
	}
	return out, rows.Err()
}

func moveOut(ctx context.Context, pool *pgxpool.Pool, orgID string, own, moveKey *sealed.Box, version string, w io.Writer) error {
	if !orgIDRe.MatchString(orgID) {
		return fmt.Errorf("org id %q isn't a uuid", orgID)
	}
	// One snapshot of the whole business.
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `SELECT set_config('app.current_org_id', $1, true)`, orgID); err != nil {
		return err
	}
	zw := zip.NewWriter(w)
	man := moveManifest{OrgID: orgID, Version: version, At: time.Now().UTC()}
	dump := func(schema, table, query string, args ...any) error {
		rows, err := tx.Query(ctx, query, args...)
		if err != nil {
			return fmt.Errorf("%s.%s: %w", schema, table, err)
		}
		var list []json.RawMessage
		for rows.Next() {
			var raw []byte
			if err := rows.Scan(&raw); err != nil {
				rows.Close()
				return err
			}
			if schema == "core" && table == "integration_credentials" {
				if raw, err = resealConfig(raw, own, moveKey); err != nil {
					rows.Close()
					return err
				}
			}
			list = append(list, raw)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
		f, err := zw.Create(schema + "/" + table + ".json")
		if err != nil {
			return err
		}
		if err := json.NewEncoder(f).Encode(list); err != nil {
			return err
		}
		man.Tables = append(man.Tables, moveTable{Schema: schema, Table: table, Rows: len(list)})
		return nil
	}
	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core.orgs WHERE id::text = $1)`, orgID).Scan(&exists); err != nil || !exists {
		return fmt.Errorf("no organisation %s", orgID)
	}
	if err := dump("core", "orgs", `SELECT to_jsonb(t) FROM core.orgs t WHERE id::text = $1`, orgID); err != nil {
		return err
	}
	if err := dump("core", "users", `SELECT to_jsonb(u) FROM core.users u WHERE id IN (SELECT user_id FROM core.memberships WHERE org_id::text = $1)`, orgID); err != nil {
		return err
	}
	tables, err := orgTables(ctx, tx)
	if err != nil {
		return err
	}
	for _, st := range tables {
		q := fmt.Sprintf(`SELECT to_jsonb(t) FROM %s.%s t WHERE org_id::text = $1`, quoteIdent(st[0]), quoteIdent(st[1]))
		if err := dump(st[0], st[1], q, orgID); err != nil {
			return err
		}
	}
	mf, err := zw.Create("manifest.json")
	if err != nil {
		return err
	}
	if err := json.NewEncoder(mf).Encode(man); err != nil {
		return err
	}
	return zw.Close()
}

// resealConfig opens a credential row's config with `from` and seals it
// with `to`.
func resealConfig(row []byte, from, to *sealed.Box) ([]byte, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(row, &m); err != nil {
		return nil, err
	}
	cfg := m["config"]
	if len(cfg) == 0 || string(cfg) == "null" {
		return row, nil
	}
	plain, err := from.Open(cfg)
	if err != nil {
		return nil, fmt.Errorf("a connected service's key: %w", err)
	}
	if cfg, err = to.Seal(plain); err != nil {
		return nil, err
	}
	m["config"] = cfg
	return json.Marshal(m)
}

// requireEmpty is always true for the command; tests share a database.
func moveIn(ctx context.Context, pool *pgxpool.Pool, bundle []byte, moveKey, own *sealed.Box, requireEmpty bool) (string, int64, error) {
	zr, err := zip.NewReader(bytes.NewReader(bundle), int64(len(bundle)))
	if err != nil {
		return "", 0, fmt.Errorf("not a move bundle: %w", err)
	}
	read := func(name string, v any) error {
		f, err := zr.Open(name)
		if err != nil {
			return err
		}
		defer f.Close()
		return json.NewDecoder(f).Decode(v)
	}
	var man moveManifest
	if err := read("manifest.json", &man); err != nil {
		return "", 0, fmt.Errorf("not a move bundle: %w", err)
	}
	if !orgIDRe.MatchString(man.OrgID) {
		return "", 0, errors.New("the bundle names no business")
	}

	tx, err := pool.Begin(ctx)
	if err != nil {
		return "", 0, err
	}
	defer tx.Rollback(ctx)
	var businesses int
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM core.orgs WHERE $1 OR id::text = $2`, requireEmpty, man.OrgID).Scan(&businesses); err != nil {
		return "", 0, err
	}
	if businesses != 0 {
		return "", 0, errors.New("this Friday already has a business; move-in needs an empty one")
	}
	if _, err := tx.Exec(ctx, `SELECT set_config('app.current_org_id', $1, true)`, man.OrgID); err != nil {
		return "", 0, err
	}

	var total int64
	insert := func(schema, table string, rows []json.RawMessage) error {
		if len(rows) == 0 {
			return nil
		}
		if schema == "core" && table == "integration_credentials" {
			for i, r := range rows {
				out, err := resealConfig(r, moveKey, own)
				if err != nil {
					return err
				}
				rows[i] = out
			}
		}
		arr, _ := json.Marshal(rows)
		q := fmt.Sprintf(`INSERT INTO %[1]s.%[2]s SELECT * FROM jsonb_populate_recordset(NULL::%[1]s.%[2]s, $1::jsonb)`, quoteIdent(schema), quoteIdent(table))
		sp, err := tx.Begin(ctx)
		if err != nil {
			return err
		}
		tag, err := sp.Exec(ctx, q, string(arr))
		if err != nil {
			sp.Rollback(ctx)
			return err
		}
		total += tag.RowsAffected()
		return sp.Commit(ctx)
	}
	load := func(t moveTable) ([]json.RawMessage, error) {
		var rows []json.RawMessage
		err := read(t.Schema+"/"+t.Table+".json", &rows)
		return rows, err
	}

	// The business, then its people: a login setup left behind for the
	// same email (no business of its own any more) gives way.
	pending := map[[2]string][]json.RawMessage{}
	for _, t := range man.Tables {
		rows, err := load(t)
		if err != nil {
			return "", 0, fmt.Errorf("%s.%s: %w", t.Schema, t.Table, err)
		}
		pending[[2]string{t.Schema, t.Table}] = rows
	}
	if err := insert("core", "orgs", pending[[2]string{"core", "orgs"}]); err != nil {
		return "", 0, fmt.Errorf("the business: %w", err)
	}
	for _, raw := range pending[[2]string{"core", "users"}] {
		var u struct {
			ID    string `json:"id"`
			Email string `json:"email"`
		}
		json.Unmarshal(raw, &u)
		if _, err := tx.Exec(ctx, `DELETE FROM core.users WHERE lower(email) = lower($1) AND id::text <> $2
			AND NOT EXISTS (SELECT 1 FROM core.memberships m WHERE m.user_id = core.users.id)`, u.Email, u.ID); err != nil {
			return "", 0, err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO core.users SELECT * FROM jsonb_populate_record(NULL::core.users, $1::jsonb) ON CONFLICT (id) DO NOTHING`, string(raw)); err != nil {
			return "", 0, fmt.Errorf("person %s: %w", u.Email, err)
		}
	}
	delete(pending, [2]string{"core", "orgs"})
	delete(pending, [2]string{"core", "users"})

	// Everything else, in passes: a table a foreign key holds back waits
	// for the next pass; no progress means the bundle doesn't fit.
	for len(pending) > 0 {
		progressed := false
		var lastErr error
		var lastName string
		for st, rows := range pending {
			if err := insert(st[0], st[1], rows); err != nil {
				lastErr, lastName = err, st[0]+"."+st[1]
				continue
			}
			delete(pending, st)
			progressed = true
		}
		if !progressed {
			return "", 0, fmt.Errorf("%s won't load: %w", lastName, lastErr)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return "", 0, err
	}
	return man.OrgID, total, nil
}
