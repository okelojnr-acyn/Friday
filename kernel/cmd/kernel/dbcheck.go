package main

import (
	"context"
	"fmt"
	"net/url"

	"strings"
	"time"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/dbcheck"
	"github.com/acyn-innovation/friday/kernel/internal/registry"
)

// runDBCheck: `kernel dbcheck` checks DATABASE_URL can hold Friday and
// prints one line per check ("ok|warn|fail <name>: <message>"). Exit 1 on
// any failure. Friday Host runs it before starting an install on a
// customer's own Postgres (plan 2.4).
func runDBCheck() int {
	raw := envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday")
	results := dbcheck.URLChecks(raw)
	print := func(rs []dbcheck.Result) {
		for _, r := range rs {
			fmt.Println(r)
		}
	}
	if dbcheck.Failed(results) {
		print(results)
		return 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	pool, err := db.Connect(ctx, raw)
	if err != nil {
		results = append(results, dbcheck.Result{Level: "fail", Name: "connect", Message: redact(err.Error(), raw)})
		print(results)
		return 1
	}
	defer pool.Close()
	schemas := []string{"core"}
	for _, a := range registry.Load() {
		schemas = append(schemas, a.Name)
	}
	results = append(results, dbcheck.Check(ctx, pool, raw, schemas)...)
	print(results)
	if dbcheck.Failed(results) {
		return 1
	}
	return 0
}

// redact keeps the URL's password out of an error message.
func redact(msg, raw string) string {
	if u, err := url.Parse(raw); err == nil && u.User != nil {
		if p, ok := u.User.Password(); ok && p != "" {
			msg = strings.ReplaceAll(msg, p, "***")
		}
	}
	return msg
}
