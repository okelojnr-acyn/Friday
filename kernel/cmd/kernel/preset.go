package main

// `kernel preset <org id> <trade> <country> <stores> <staff>`: shapes a new
// business from Friday Host's onboarding answers (docs/ONBOARDING-PLAN.md
// in Friday Host): the apps its trade uses, its country's currency, VAT
// rate and time zone, a spending policy for its size, and a store per
// branch. Run once, right after `kernel bootstrap`; every value stays
// editable in Business settings and Apps.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acyn-innovation/friday/kernel/internal/db"
	"github.com/acyn-innovation/friday/kernel/internal/org"
)

// tradeApps: the apps each trade starts with. Web3 is never on by default.
var tradeApps = map[string][]string{
	"shop":        {"crm", "invoicing", "inventory", "accounting", "minions"},
	"supermarket": {"crm", "invoicing", "inventory", "accounting", "minions"},
	"liquor":      {"crm", "invoicing", "inventory", "accounting", "minions"},
	"fashion":     {"crm", "invoicing", "inventory", "accounting", "minions"},
	"pharmacy":    {"crm", "invoicing", "inventory", "accounting", "minions"},
	"restaurant":  {"crm", "invoicing", "inventory", "accounting", "minions"},
	"wholesale":   {"crm", "invoicing", "inventory", "accounting", "minions", "fleets"},
	"services":    {"crm", "invoicing", "projects", "accounting", "minions"},
	"rentals":     {"crm", "invoicing", "projects", "accounting", "minions"},
	"ngo":         {"crm", "invoicing", "projects", "accounting", "minions"},
	"other":       {"crm", "invoicing", "projects", "inventory", "accounting", "minions", "fleets"},
}

// countryDefaults: currency, standard VAT rate (basis points) and time zone.
// shortcut: the standard rate only; reduced and zero rates stay per product.
var countryDefaults = map[string]struct {
	currency string
	vatBP    int
	zone     string
}{
	"KE":    {"KES", 1600, "Africa/Nairobi"},
	"UG":    {"UGX", 1800, "Africa/Kampala"},
	"TZ":    {"TZS", 1800, "Africa/Dar_es_Salaam"},
	"RW":    {"RWF", 1800, "Africa/Kigali"},
	"NG":    {"NGN", 750, "Africa/Lagos"},
	"GH":    {"GHS", 1500, "Africa/Accra"},
	"ZA":    {"ZAR", 1500, "Africa/Johannesburg"},
	"ID":    {"IDR", 1100, "Asia/Jakarta"},
	"OTHER": {"USD", 0, ""},
}

// spendingFor: Simple for one store and a handful of staff, Strict from 4
// stores or 50 staff, Standard otherwise.
func spendingFor(stores, staff int) string {
	switch {
	case stores <= 1 && staff <= 5:
		return "simple"
	case stores >= 4 || staff >= 50:
		return "strict"
	}
	return "standard"
}

func runPreset(args []string) error {
	if len(args) != 5 {
		return errors.New("usage: kernel preset <org id> <trade> <country> <stores> <staff>")
	}
	stores, err1 := strconv.Atoi(args[3])
	staff, err2 := strconv.Atoi(args[4])
	if err1 != nil || err2 != nil || stores < 1 || staff < 1 {
		return errors.New("stores and staff are whole numbers from 1")
	}
	ctx := context.Background()
	pool, err := db.Connect(ctx, envOr("DATABASE_URL", "postgres://friday:friday@localhost:5432/friday"))
	if err != nil {
		return fmt.Errorf("db connect: %w", err)
	}
	defer pool.Close()
	if err := preset(ctx, pool, args[0], args[1], strings.ToUpper(args[2]), stores, staff); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "preset %s for a %s business in %s, %d stores, %d staff\n", args[0], args[1], args[2], stores, staff)
	return nil
}

func preset(ctx context.Context, pool *pgxpool.Pool, orgID, trade, country string, stores, staff int) error {
	apps, ok := tradeApps[trade]
	if !ok {
		return fmt.Errorf("unknown trade %q", trade)
	}
	c, ok := countryDefaults[country]
	if !ok {
		c = countryDefaults["OTHER"]
	}
	policy, _ := json.Marshal(org.SpendingPresets[spendingFor(stores, staff)])
	stores = min(stores, 20) // the rest are added in Business settings

	tx, err := pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	tag, err := tx.Exec(ctx, `
		UPDATE core.orgs SET currency = $2, tax_rate_bp = $3, time_zone = $4, spending_policy = $5 WHERE id::text = $1`,
		orgID, c.currency, c.vatBP, c.zone, policy)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return fmt.Errorf("no organisation %s", orgID)
	}
	if _, err := tx.Exec(ctx, `DELETE FROM core.app_installs WHERE org_id::text = $1 AND NOT (app_name = ANY($2))`, orgID, apps); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO core.app_installs (org_id, app_name)
		SELECT $1::uuid, a FROM unnest($2::text[]) a WHERE a IN (SELECT name FROM core.apps) ON CONFLICT DO NOTHING`, orgID, apps); err != nil {
		return err
	}
	for n := 2; n <= stores; n++ {
		if _, err := tx.Exec(ctx, `INSERT INTO core.locations (org_id, name) VALUES ($1::uuid, $2) ON CONFLICT DO NOTHING`,
			orgID, fmt.Sprintf("Store %d", n)); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}
