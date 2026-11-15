// Package orgexport writes everything one organisation has in Friday as a
// zip: one CSV per table that has an org_id column (found from
// information_schema, so a new app's tables are never forgotten), the
// org's people without any secrets, and manifest.json with row counts and
// a sha256 per file. Rows are read with app.current_org_id set, so
// Postgres row-level security enforces the org boundary as well as the
// WHERE clause.
package orgexport

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

var uuidRe = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// Secret or transient tables that have an org_id but never leave Friday.
var skip = map[string]bool{
	"core.integration_credentials": true, // API keys of connected services
	"core.guss_service":            true, // Guss's key (hash) and access
	"core.guss_link_codes":         true, // short-lived codes
	"core.webauthn_credentials":    true, // passkeys
	"core.webauthn_challenges":     true,
	"core.otp_codes":               true,
}

// Included reports whether schema.table is exported.
func Included(schema, table string) bool {
	if schema == "pg_catalog" || schema == "information_schema" || strings.HasPrefix(schema, "pg_") {
		return false
	}
	return !skip[schema+"."+table]
}

type fileInfo struct {
	Name   string `json:"name"`
	Rows   int    `json:"rows"`
	SHA256 string `json:"sha256"`
}

type manifest struct {
	OrgID       string     `json:"org_id"`
	OrgName     string     `json:"org_name"`
	Version     string     `json:"friday_version"`
	GeneratedAt time.Time  `json:"generated_at"`
	Files       []fileInfo `json:"files"`
	Note        string     `json:"note"`
}

func quoteIdent(s string) string { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }

// Write streams the org's export as a zip to w.
func Write(ctx context.Context, pool *pgxpool.Pool, orgID, version string, w io.Writer) error {
	if !uuidRe.MatchString(orgID) {
		return fmt.Errorf("org id %q isn't a uuid", orgID)
	}
	var orgName string
	if err := pool.QueryRow(ctx, `SELECT name FROM core.orgs WHERE id = $1`, orgID).Scan(&orgName); err != nil {
		return fmt.Errorf("no organisation %s", orgID)
	}

	rows, err := pool.Query(ctx, `
		SELECT table_schema, table_name FROM information_schema.columns
		WHERE column_name = 'org_id'
		  AND table_name IN (SELECT table_name FROM information_schema.tables t
		                     WHERE t.table_schema = columns.table_schema AND t.table_type = 'BASE TABLE')
		ORDER BY table_schema, table_name`)
	if err != nil {
		return err
	}
	var tables [][2]string
	for rows.Next() {
		var s, t string
		if rows.Scan(&s, &t) == nil && Included(s, t) {
			tables = append(tables, [2]string{s, t})
		}
	}
	rows.Close()

	zw := zip.NewWriter(w)
	man := manifest{OrgID: orgID, OrgName: orgName, Version: version, GeneratedAt: time.Now().UTC(),
		Note: "One CSV per table (rows of this organisation only). people.csv lists members without passwords, passkeys or tokens."}

	add := func(name string, data []byte, rowCount int) error {
		f, err := zw.Create(name)
		if err != nil {
			return err
		}
		if _, err := f.Write(data); err != nil {
			return err
		}
		sum := sha256.Sum256(data)
		man.Files = append(man.Files, fileInfo{Name: name, Rows: rowCount, SHA256: hex.EncodeToString(sum[:])})
		return nil
	}

	for _, st := range tables {
		data, n, err := copyTable(ctx, pool, orgID, st[0], st[1])
		if err != nil {
			return fmt.Errorf("%s.%s: %w", st[0], st[1], err)
		}
		if err := add(st[0]+"/"+st[1]+".csv", data, n); err != nil {
			return err
		}
	}

	people, n, err := peopleCSV(ctx, pool, orgID)
	if err != nil {
		return err
	}
	if err := add("people.csv", people, n); err != nil {
		return err
	}

	sort.Slice(man.Files, func(i, j int) bool { return man.Files[i].Name < man.Files[j].Name })
	mf, err := zw.Create("manifest.json")
	if err != nil {
		return err
	}
	enc := json.NewEncoder(mf)
	enc.SetIndent("", "  ")
	if err := enc.Encode(man); err != nil {
		return err
	}
	return zw.Close()
}

// copyTable runs COPY ... TO STDOUT for one table inside a transaction
// with the org set for row-level security.
func copyTable(ctx context.Context, pool *pgxpool.Pool, orgID, schema, table string) ([]byte, int, error) {
	conn, err := pool.Acquire(ctx)
	if err != nil {
		return nil, 0, err
	}
	defer conn.Release()
	tx, err := conn.Begin(ctx)
	if err != nil {
		return nil, 0, err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `SELECT set_config('app.current_org_id', $1, true)`, orgID); err != nil {
		return nil, 0, err
	}
	var buf bytes.Buffer
	// orgID is a validated uuid; identifiers are quoted.
	sql := fmt.Sprintf(`COPY (SELECT * FROM %s.%s WHERE org_id = '%s') TO STDOUT WITH (FORMAT csv, HEADER true)`,
		quoteIdent(schema), quoteIdent(table), orgID)
	tag, err := tx.Conn().PgConn().CopyTo(ctx, &buf, sql)
	if err != nil {
		return nil, 0, err
	}
	return buf.Bytes(), int(tag.RowsAffected()), nil
}

func peopleCSV(ctx context.Context, pool *pgxpool.Pool, orgID string) ([]byte, int, error) {
	rows, err := pool.Query(ctx, `
		SELECT u.id, u.email, u.full_name, m.role, m.created_at
		FROM core.memberships m JOIN core.users u ON u.id = m.user_id
		WHERE m.org_id = $1 ORDER BY m.created_at`, orgID)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	var buf bytes.Buffer
	cw := csv.NewWriter(&buf)
	cw.Write([]string{"user_id", "email", "full_name", "role", "member_since"})
	n := 0
	for rows.Next() {
		var id, email, name, role string
		var since time.Time
		if err := rows.Scan(&id, &email, &name, &role, &since); err != nil {
			return nil, 0, err
		}
		cw.Write([]string{id, email, name, role, since.UTC().Format(time.RFC3339)})
		n++
	}
	cw.Flush()
	return buf.Bytes(), n, rows.Err()
}

// Handler serves POST /admin/orgs/{id}/export to that org's owners (a
// Friday Host owner signs in as one through SSO). Assistant tokens (Guss)
// never reach it: the kernel only lets them through to app routes.
func Handler(pool *pgxpool.Pool, version string, claimsOf func(*http.Request) (orgID, role, via string, ok bool)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		orgID, role, via, ok := claimsOf(r)
		id := r.PathValue("id")
		if !ok || via != "" || role != "owner" || orgID != id {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			w.Write([]byte(`{"error":"only this organisation's owners can export it"}`))
			return
		}
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("Content-Disposition", `attachment; filename="friday-export-`+time.Now().UTC().Format("2006-01-02")+`.zip"`)
		if err := Write(r.Context(), pool, id, version, w); err != nil {
			// Headers are gone by now; the truncated zip won't open, and
			// the log says why.
			log.Printf("export %s: %v", id, err)
		}
	}
}
