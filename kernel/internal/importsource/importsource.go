// Package importsource reads a customer's existing Postgres for the import
// screen (plan 2.4): list its tables, then page through one table's rows
// by a key column. The browser maps those rows to an app's import target
// and sends them to the app (friday_common/importer.py). The connection is
// read-only, nothing is stored, and the URL is never logged.
package importsource

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	maxTables = 300
	maxRows   = 500
)

// Handler serves POST /orgs/import/source.
type Handler struct {
	// AllowPrivate lets a self-hosted install read a database on its own
	// network (FRIDAY_IMPORT_ALLOW_PRIVATE=true). Off by default: on a
	// shared install it would let an admin reach Friday's own database or
	// another internal service.
	AllowPrivate bool
	// Claims returns the caller's org role and whether an assistant is
	// acting for them.
	Claims func(*http.Request) (role, via string, ok bool)
}

type request struct {
	URL   string  `json:"url"`
	Table string  `json:"table"` // "schema.table"; empty lists tables
	Key   string  `json:"key"`   // column that orders and identifies rows
	After *string `json:"after"`
	Limit int     `json:"limit"`
}

type Column struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type Table struct {
	Name          string   `json:"name"` // schema.table
	Columns       []Column `json:"columns"`
	EstimatedRows int64    `json:"estimated_rows"`
}

type Row struct {
	Key    string         `json:"key"`
	Values map[string]any `json:"values"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	role, via, ok := h.Claims(r)
	if !ok || via != "" || (role != "owner" && role != "admin") {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "only owners and admins can import"})
		return
	}
	var req request
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 45*time.Second)
	defer cancel()
	conn, err := h.connect(ctx, req.URL)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": redact(err.Error(), req.URL)})
		return
	}
	defer conn.Close(context.WithoutCancel(ctx))

	tables, err := listTables(ctx, conn)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": redact(err.Error(), req.URL)})
		return
	}
	if req.Table == "" {
		writeJSON(w, http.StatusOK, map[string]any{"tables": tables})
		return
	}
	var table *Table
	for i := range tables {
		if tables[i].Name == req.Table {
			table = &tables[i]
		}
	}
	if table == nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no table " + req.Table + " in that database"})
		return
	}
	keyOK := false
	for _, c := range table.Columns {
		keyOK = keyOK || c.Name == req.Key
	}
	if !keyOK {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "pick the column that identifies each row"})
		return
	}
	rows, next, err := readRows(ctx, conn, *table, req.Key, req.After, req.Limit)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": redact(err.Error(), req.URL)})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"rows": rows, "next": next})
}

// connect opens one read-only connection. Every address it dials is
// checked, so a host name that resolves to a private address (or changes
// to one after a first lookup) is refused too.
func (h *Handler) connect(ctx context.Context, raw string) (*pgx.Conn, error) {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.Hostname() == "" {
		return nil, errors.New("use a URL like postgres://user:password@host:5432/dbname")
	}
	cfg, err := pgx.ParseConfig(raw)
	if err != nil {
		return nil, errors.New("that database URL can't be read")
	}
	cfg.ConnectTimeout = 10 * time.Second
	cfg.RuntimeParams["default_transaction_read_only"] = "on"
	cfg.RuntimeParams["statement_timeout"] = "30000"
	cfg.RuntimeParams["application_name"] = "friday-import"
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	cfg.DialFunc = func(ctx context.Context, network, addr string) (net.Conn, error) {
		if !h.AllowPrivate {
			host, _, _ := net.SplitHostPort(addr)
			ip := net.ParseIP(host)
			if ip == nil || blocked(ip) {
				return nil, fmt.Errorf("%s is a private or local address; Friday imports only from databases on the internet", host)
			}
		}
		return dialer.DialContext(ctx, network, addr)
	}
	return pgx.ConnectConfig(ctx, cfg)
}

func blocked(ip net.IP) bool {
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() ||
		ip.IsUnspecified() || ip.IsMulticast() || ip.IsInterfaceLocalMulticast() ||
		(ip.To4() != nil && ip.To4()[0] == 100 && ip.To4()[1]&0xc0 == 64) // 100.64.0.0/10
}

func listTables(ctx context.Context, conn *pgx.Conn) ([]Table, error) {
	rows, err := conn.Query(ctx, `
		SELECT c.table_schema || '.' || c.table_name, c.column_name, c.data_type,
		       COALESCE((SELECT GREATEST(cl.reltuples, 0)::bigint FROM pg_class cl JOIN pg_namespace n ON n.oid = cl.relnamespace
		                 WHERE n.nspname = c.table_schema AND cl.relname = c.table_name), 0)
		FROM information_schema.columns c
		JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
		WHERE t.table_type IN ('BASE TABLE', 'VIEW')
		  AND c.table_schema NOT IN ('pg_catalog', 'information_schema') AND c.table_schema NOT LIKE 'pg\_%'
		ORDER BY 1, c.ordinal_position`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Table
	for rows.Next() {
		var name, col, typ string
		var est int64
		if err := rows.Scan(&name, &col, &typ, &est); err != nil {
			return nil, err
		}
		if len(out) == 0 || out[len(out)-1].Name != name {
			if len(out) == maxTables {
				break
			}
			out = append(out, Table{Name: name, EstimatedRows: est})
		}
		out[len(out)-1].Columns = append(out[len(out)-1].Columns, Column{Name: col, Type: typ})
	}
	return out, rows.Err()
}

// readRows pages by the key column's text form, so any column type works
// and the same paging repeats exactly on a re-run.
func readRows(ctx context.Context, conn *pgx.Conn, t Table, key string, after *string, limit int) ([]Row, *string, error) {
	if limit <= 0 || limit > maxRows {
		limit = maxRows
	}
	schema, name, _ := strings.Cut(t.Name, ".")
	tbl := pgx.Identifier{schema, name}.Sanitize()
	// Byte order (COLLATE "C") in both the comparison and the sort, so
	// paging never skips or repeats a row whatever the database's locale.
	k := "(t." + pgx.Identifier{key}.Sanitize() + `::text COLLATE "C")`
	q := fmt.Sprintf(`SELECT %[1]s, to_jsonb(t) FROM %[2]s t WHERE %[1]s IS NOT NULL AND ($1::text IS NULL OR %[1]s > $1) ORDER BY %[1]s LIMIT $2`, k, tbl)
	rows, err := conn.Query(ctx, q, after, limit)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	out := []Row{}
	for rows.Next() {
		var row Row
		var raw []byte
		if err := rows.Scan(&row.Key, &raw); err != nil {
			return nil, nil, err
		}
		if err := json.Unmarshal(raw, &row.Values); err != nil {
			return nil, nil, err
		}
		out = append(out, row)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	var next *string
	if len(out) == limit {
		next = &out[len(out)-1].Key
	}
	return out, next, nil
}

// redact keeps the URL and its password out of an error message.
func redact(msg, raw string) string {
	if raw != "" {
		msg = strings.ReplaceAll(msg, raw, "***")
	}
	if u, err := url.Parse(raw); err == nil && u.User != nil {
		if p, ok := u.User.Password(); ok && p != "" {
			msg = strings.ReplaceAll(msg, p, "***")
		}
	}
	return msg
}
