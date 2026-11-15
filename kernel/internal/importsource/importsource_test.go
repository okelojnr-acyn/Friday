package importsource

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

func TestBlockedAddresses(t *testing.T) {
	for _, s := range []string{"127.0.0.1", "10.1.2.3", "172.18.0.5", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::1", "fd00::1", "0.0.0.0"} {
		if !blocked(net.ParseIP(s)) {
			t.Errorf("%s should be blocked", s)
		}
	}
	for _, s := range []string{"8.8.8.8", "2.28.133.174", "2606:4700::1"} {
		if blocked(net.ParseIP(s)) {
			t.Errorf("%s should be allowed", s)
		}
	}
}

func call(t *testing.T, h *Handler, body map[string]any) (int, map[string]any) {
	t.Helper()
	b, _ := json.Marshal(body)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/orgs/import/source", bytes.NewReader(b)))
	var out map[string]any
	json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

func admin(*http.Request) (string, string, bool) { return "admin", "", true }

func TestOnlyPeopleWhoRunTheOrgCanRead(t *testing.T) {
	for _, c := range []func(*http.Request) (string, string, bool){
		func(*http.Request) (string, string, bool) { return "member", "", true },
		func(*http.Request) (string, string, bool) { return "owner", "guss", true },
	} {
		if code, _ := call(t, &Handler{Claims: c}, map[string]any{"url": "postgres://u:p@8.8.8.8/x"}); code != http.StatusForbidden {
			t.Fatalf("want 403, got %d", code)
		}
	}
}

func TestPrivateDatabasesAreRefusedAndThePasswordNeverEchoed(t *testing.T) {
	code, out := call(t, &Handler{Claims: admin}, map[string]any{"url": "postgres://u:hunter2secret@127.0.0.1:5432/x"})
	msg, _ := out["error"].(string)
	if code != http.StatusBadGateway || !strings.Contains(msg, "private or local") || strings.Contains(msg, "hunter2secret") {
		t.Fatalf("got %d %q", code, msg)
	}
}

func TestListAndPageOnRealPostgres(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		if os.Getenv("CI") != "" {
			t.Fatal("KERNEL_TEST_DATABASE_URL must be set on CI")
		}
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)
	conn.Exec(ctx, `DROP SCHEMA IF EXISTS oldshop CASCADE`)
	if _, err := conn.Exec(ctx, `
		CREATE SCHEMA oldshop;
		CREATE TABLE oldshop.items (code text PRIMARY KEY, title text, price numeric);
		INSERT INTO oldshop.items SELECT 'I-' || lpad(g::text, 3, '0'), 'Item ' || g, g * 1.5 FROM generate_series(1, 7) g;
		INSERT INTO oldshop.items VALUES ('a-lower', 'Lower', 1);`); err != nil {
		t.Fatal(err)
	}
	defer conn.Exec(ctx, `DROP SCHEMA IF EXISTS oldshop CASCADE`)

	h := &Handler{Claims: admin, AllowPrivate: true}
	code, out := call(t, h, map[string]any{"url": dsn})
	if code != http.StatusOK || !strings.Contains(mustJSON(out), `"oldshop.items"`) {
		t.Fatalf("tables: %d %v", code, out)
	}

	var keys []string
	var after any
	for page := 0; page < 10; page++ {
		code, out = call(t, h, map[string]any{"url": dsn, "table": "oldshop.items", "key": "code", "after": after, "limit": 3})
		if code != http.StatusOK {
			t.Fatalf("rows: %d %v", code, out)
		}
		for _, r := range out["rows"].([]any) {
			row := r.(map[string]any)
			keys = append(keys, row["key"].(string))
			if row["values"].(map[string]any)["title"] == nil {
				t.Fatal("values must carry every column")
			}
		}
		if out["next"] == nil {
			break
		}
		after = out["next"]
	}
	if len(keys) != 8 {
		t.Fatalf("want 8 rows over the pages, got %v", keys)
	}

	// The connection is read-only.
	code, _ = call(t, h, map[string]any{"url": dsn, "table": "oldshop.items; DROP TABLE oldshop.items", "key": "code"})
	if code != http.StatusNotFound {
		t.Fatalf("unknown table name must be refused, got %d", code)
	}
	if code, _ = call(t, h, map[string]any{"url": dsn, "table": "oldshop.items", "key": "nope"}); code != http.StatusBadRequest {
		t.Fatalf("unknown key column: %d", code)
	}
}

func TestConnectionIsReadOnly(t *testing.T) {
	dsn := os.Getenv("KERNEL_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("KERNEL_TEST_DATABASE_URL not set")
	}
	conn, err := (&Handler{AllowPrivate: true}).connect(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(context.Background())
	if _, err := conn.Exec(context.Background(), `CREATE TABLE friday_import_should_fail (x int)`); err == nil {
		t.Fatal("writes must fail on the import connection")
	}
}

func mustJSON(v any) string { b, _ := json.Marshal(v); return string(b) }
