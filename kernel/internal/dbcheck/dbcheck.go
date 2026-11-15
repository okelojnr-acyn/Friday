// Package dbcheck answers "can Friday run on this Postgres?" before an
// install starts on a database the customer brought (plan 2.4). It never
// prints the URL or anything from it.
package dbcheck

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Result is one check: Level is "ok", "warn" or "fail".
type Result struct {
	Level, Name, Message string
}

func (r Result) String() string { return r.Level + " " + r.Name + ": " + r.Message }

// Failed reports whether any result is a failure.
func Failed(rs []Result) bool {
	for _, r := range rs {
		if r.Level == "fail" {
			return true
		}
	}
	return false
}

// LocalHost: the bundled database (compose service "postgres") or this
// machine. Traffic to those never leaves the server, so TLS isn't asked for.
func LocalHost(host string) bool {
	switch host {
	case "", "postgres", "localhost", "127.0.0.1", "::1":
		return true
	}
	return false
}

// URLChecks look at the URL alone, before connecting.
func URLChecks(raw string) []Result {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") {
		return []Result{{"fail", "url", "use a postgres:// URL, e.g. postgres://user:password@host:5432/dbname?sslmode=require"}}
	}
	if u.User == nil || u.User.Username() == "" || strings.TrimPrefix(u.Path, "/") == "" {
		return []Result{{"fail", "url", "the URL needs a user and a database name"}}
	}
	if LocalHost(u.Hostname()) {
		return []Result{{"ok", "url", "database on this server"}}
	}
	switch u.Query().Get("sslmode") {
	case "require", "verify-ca", "verify-full":
		return []Result{{"ok", "url", "TLS required (sslmode=" + u.Query().Get("sslmode") + ")"}}
	}
	return []Result{{"fail", "url", "add ?sslmode=require (or verify-full) so the password never crosses the internet unencrypted"}}
}

// Check runs every check against a connected pool. schemas are the
// schemas Friday will own (core plus one per app).
func Check(ctx context.Context, pool *pgxpool.Pool, rawURL string, schemas []string) []Result {
	var out []Result
	add := func(level, name, format string, a ...any) {
		out = append(out, Result{level, name, fmt.Sprintf(format, a...)})
	}

	var verStr string
	if err := pool.QueryRow(ctx, `SHOW server_version_num`).Scan(&verStr); err != nil {
		add("fail", "version", "could not read the server version")
		return out
	}
	ver, _ := strconv.Atoi(verStr)
	if ver < 140000 {
		add("fail", "version", "Friday needs PostgreSQL 14 or newer; this is %d.%d", ver/10000, ver%10000)
	} else if ver >= 170000 {
		// Backups run pg_dump from the bundled postgres:16 image, and
		// pg_dump refuses a newer server.
		add("warn", "version", "PostgreSQL %d works, but Friday's nightly backup can only dump 16 or older; back this database up yourself", ver/10000)
	} else {
		add("ok", "version", "PostgreSQL %d", ver/10000)
	}

	host := ""
	if u, err := url.Parse(rawURL); err == nil {
		host = u.Hostname()
	}
	if !LocalHost(host) {
		var ssl bool
		if err := pool.QueryRow(ctx, `SELECT COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false)`).Scan(&ssl); err != nil || !ssl {
			add("fail", "tls", "the connection isn't encrypted; turn on TLS on the server")
		} else {
			add("ok", "tls", "connection encrypted")
		}
	}

	var super bool
	pool.QueryRow(ctx, `SELECT rolsuper FROM pg_roles WHERE rolname = current_user`).Scan(&super)
	if super {
		add("warn", "role", "this is a superuser; Friday works, but a role of its own is safer (superusers skip row-level security)")
	}

	var canCreate bool
	if err := pool.QueryRow(ctx, `SELECT has_database_privilege(current_database(), 'CREATE')`).Scan(&canCreate); err != nil {
		add("fail", "privileges", "could not read this role's privileges")
		return out
	}
	missing := 0
	for _, s := range schemas {
		var exists, usable, isFriday bool
		var others int
		err := pool.QueryRow(ctx, `
			SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = $1),
			       COALESCE((SELECT has_schema_privilege(oid, 'CREATE') AND has_schema_privilege(oid, 'USAGE') FROM pg_namespace WHERE nspname = $1), false),
			       EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = $1 AND tablename = 'schema_migrations'),
			       (SELECT count(*) FROM pg_tables WHERE schemaname = $1)`, s).Scan(&exists, &usable, &isFriday, &others)
		if err != nil {
			add("fail", "schema "+s, "could not inspect it")
			continue
		}
		switch {
		case !exists:
			missing++
		case !isFriday && others > 0:
			add("fail", "schema "+s, "already exists with %d other tables; Friday needs this name for its own tables. Use another database", others)
		case !usable:
			add("fail", "schema "+s, "exists but this role can't create tables in it")
		}
	}
	if missing > 0 && !canCreate {
		add("fail", "privileges", "this role can't create schemas; run: GRANT CREATE ON DATABASE <db> TO <role>")
	} else {
		add("ok", "privileges", "Friday can create its %d schemas", len(schemas))
	}
	return out
}
