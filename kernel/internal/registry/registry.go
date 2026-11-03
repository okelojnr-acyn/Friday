// Package registry is the kernel's app registry: the static list of app
// services this deployment knows about, where to reach them, and how to
// describe them in the launcher/apps-catalog UI. Adding an app to a
// deployment means adding one entry here (or one env var block) -- not
// touching the web shell, which renders the catalog from this list plus
// each app's own /schema endpoint.
package registry

import (
	"os"
)

type App struct {
	Name        string
	Label       string
	Description string
	Icon        string
	Category    string
	BaseURL     string
}

func Load() []App {
	return []App{
		{
			Name:        "crm",
			Label:       "CRM & Sales",
			Description: "Track leads and opportunities through to a won deal.",
			Icon:        "target",
			Category:    "sales",
			BaseURL:     envOr("APP_CRM_URL", "http://localhost:8001"),
		},
		{
			Name:        "invoicing",
			Label:       "Invoicing",
			Description: "Customers, invoices, and payment status.",
			Icon:        "receipt",
			Category:    "finance",
			BaseURL:     envOr("APP_INVOICING_URL", "http://localhost:8002"),
		},
		{
			Name:        "projects",
			Label:       "Projects & Helpdesk",
			Description: "Tasks, kanban boards, and a support ticket queue.",
			Icon:        "kanban",
			Category:    "work",
			BaseURL:     envOr("APP_PROJECTS_URL", "http://localhost:8003"),
		},
		{
			Name:        "inventory",
			Label:       "Inventory",
			Description: "Products, stock on hand, and a stock move ledger.",
			Icon:        "box",
			Category:    "operations",
			BaseURL:     envOr("APP_INVENTORY_URL", "http://localhost:8004"),
		},
		{
			Name:        "web3",
			Label:       "Web3",
			Description: "Mini-apps: a business wallet via Acyn Wallet, plus live market data.",
			Icon:        "wallet",
			Category:    "finance",
			BaseURL:     envOr("APP_WEB3_URL", "http://localhost:8005"),
		},
		{
			Name:        "accounting",
			Label:       "Accounting",
			Description: "A double-entry ledger -- chart of accounts, journal entries, and reports.",
			Icon:        "ledger",
			Category:    "finance",
			BaseURL:     envOr("APP_ACCOUNTING_URL", "http://localhost:8006"),
		},
		{
			Name:        "minions",
			Label:       "Minions",
			Description: "Employee workspace: tasks, expense claims, and crypto payroll via Acyn Wallet.",
			Icon:        "users",
			Category:    "work",
			BaseURL:     envOr("APP_MINIONS_URL", "http://localhost:8007"),
		},
		{
			Name:        "fleets",
			Label:       "Fleets",
			Description: "Vehicles, drivers, and maintenance/fuel logs.",
			Icon:        "truck",
			Category:    "operations",
			BaseURL:     envOr("APP_FLEETS_URL", "http://localhost:8008"),
		},
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
