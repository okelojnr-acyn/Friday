import type { IconName } from "../ui/Icon";

/** One entry in an app's left rail. `hint` is the one small line shown
 * above the page (UI standard, plan 17: hints small, where needed). */
export interface NavItem {
  label: string;
  to: string;
  icon: IconName;
  hint?: string;
  /** A separate HTML entry (the till, the staff app): a full navigation. */
  external?: boolean;
  /** A queue someone must act on: the rail shows how many are waiting.
   * Kept to the few that need a person (UI standard: badges everywhere
   * stop being seen). */
  waiting?: { path: string; statuses: string[] };
}
export interface AppNav {
  /** The registry app whose API the resources live in. */
  app: string;
  label: string;
  sections: [string, NavItem[]][];
}

/** Each app's rail, grouped the way people in that trade work (owner,
 * 2026-11-22: the Apps & integrations layout is the foundation; each app
 * builds on its profession's patterns):
 * - CRM: Pipedrive/HubSpot (pipeline first, deals, activities);
 * - Invoicing: Xero/QuickBooks sales (receivables overview, invoices,
 *   quotes, customers; the till; tax);
 * - Inventory: Shopify/Zoho (stock, then purchasing, then setup);
 * - Accounting: Xero/QuickBooks (reports, books, banking, close & tax);
 * - Projects: Linear/Jira/Zendesk (work, support, time);
 * - Fleets: Fleetio/Samsara (fleet, deliveries, running costs);
 * - People: BambooHR/Gusto (team, pay, work), Minions' admin side;
 * - Web3: treasury first, then the market. */
export const APP_NAV: Record<string, AppNav> = {
  crm: {
    app: "crm",
    label: "CRM & Sales",
    sections: [
      ["Sell", [
        { label: "Pipeline", to: "/crm", icon: "funnel", hint: "Drag a deal to its next stage; the column totals show what each stage is worth." },
        { label: "Deals", to: "/crm/opportunity", icon: "target" },
        { label: "Activities", to: "/crm/activity", icon: "calendar", hint: "Calls, meetings and follow-ups. Overdue ones show on the deal in red." },
      ]],
      ["Contacts", [{ label: "Customers", to: "/invoicing/customer", icon: "users" }]],
    ],
  },
  invoicing: {
    app: "invoicing",
    label: "Invoicing",
    sections: [
      ["Overview", [{ label: "Receivables", to: "/invoicing", icon: "trend-up", hint: "Who owes you, and for how long." }]],
      ["Sales", [
        { label: "Invoices", to: "/invoicing/invoice", icon: "invoice" },
        { label: "Quotes", to: "/invoicing/quote", icon: "receipt", hint: "A quote becomes an invoice when the customer accepts it." },
        { label: "Customers", to: "/invoicing/customer", icon: "users" },
      ]],
      ["Point of sale", [
        { label: "Open the till", to: "/pos.html", icon: "storefront", external: true },
        { label: "Till shifts", to: "/invoicing/pos_shift", icon: "clock" },
      ]],
      ["Tax", [{ label: "eTIMS filing", to: "/etims", icon: "shield-check" }]],
    ],
  },
  inventory: {
    app: "inventory",
    label: "Inventory",
    sections: [
      ["Stock", [
        { label: "Products", to: "/inventory/product", icon: "box" },
        { label: "Stock moves", to: "/inventory/stock_move", icon: "history", hint: "Every unit in or out, and why: sales, receipts, transfers, counts." },
        { label: "Warehouses", to: "/inventory/warehouse", icon: "storefront" },
        { label: "Online orders", to: "/inventory/online-orders", icon: "receipt", hint: "Orders from your online shop: get them ready, hand them over.", waiting: { path: "/api/inventory/shop_orders", statuses: ["paid", "ready"] } },
      ]],
      ["Purchasing", [
        { label: "Purchase orders", to: "/inventory/purchase_order", icon: "receipt" },
        { label: "Suppliers", to: "/inventory/supplier", icon: "truck" },
      ]],
      ["Setup", [{ label: "Units of measure", to: "/inventory/unit_of_measure", icon: "percent" }]],
    ],
  },
  accounting: {
    app: "accounting",
    label: "Accounting",
    sections: [
      ["Reports", [
        { label: "Overview", to: "/accounting", icon: "calculator", hint: "The money you have, who owes you, what you owe, and this month so far." },
        { label: "Reports", to: "/accounting/reports", icon: "trend-up", hint: "Profit & loss, balance sheet and trial balance, from the same books." },
      ]],
      ["Books", [
        { label: "Journal entries", to: "/accounting/journal_entry", icon: "ledger", hint: "Sales, payments and payouts post here by themselves; add manual entries for the rest.", waiting: { path: "/api/accounting/journal_entries", statuses: ["pending"] } },
        { label: "Chart of accounts", to: "/accounting/account", icon: "database" },
      ]],
      ["Banking", [
        { label: "Bank accounts", to: "/accounting/bank_account", icon: "wallet" },
        { label: "Bank transactions", to: "/accounting/bank_transaction", icon: "credit-card", hint: "Match each line to an entry to reconcile." },
      ]],
      ["Close & tax", [
        { label: "Fiscal periods", to: "/accounting/fiscal_period", icon: "calendar", hint: "Close a period to lock its entries." },
        { label: "eTIMS filing", to: "/etims", icon: "shield-check" },
      ]],
    ],
  },
  projects: {
    app: "projects",
    label: "Projects & Helpdesk",
    sections: [
      ["Work", [
        { label: "Projects", to: "/projects/project", icon: "kanban" },
        { label: "Tasks", to: "/projects/task", icon: "kanban" },
      ]],
      ["Support", [{ label: "Helpdesk tickets", to: "/projects/ticket", icon: "ticket" }]],
      ["Time", [{ label: "Time entries", to: "/projects/time_entry", icon: "clock" }]],
    ],
  },
  fleets: {
    app: "fleets",
    label: "Fleets",
    sections: [
      ["Fleet", [
        { label: "Vehicles", to: "/fleets/vehicle", icon: "truck" },
        { label: "Drivers", to: "/fleets/driver", icon: "user" },
      ]],
      ["Deliveries", [{ label: "Parcels", to: "/fleets/parcel", icon: "box", hint: "Scan a parcel in, out, delivered or returned; its history follows it." }]],
      ["Running costs", [
        { label: "Fuel logs", to: "/fleets/fuel_log", icon: "receipt" },
        { label: "Maintenance", to: "/fleets/maintenance_log", icon: "calculator" },
      ]],
    ],
  },
  people: {
    app: "minions",
    label: "People",
    sections: [
      ["Team", [
        { label: "Everyone", to: "/people", icon: "users", hint: "Click a person to change their role, jobs, locations or who they report to." },
        { label: "Invites", to: "/people?tab=invites", icon: "mail" },
        { label: "Locations", to: "/people?tab=locations", icon: "storefront" },
        { label: "Roles & access", to: "/people?tab=roles", icon: "shield-check" },
      ]],
      ["Pay", [
        { label: "Payroll", to: "/people/payroll_run", icon: "wallet" },
        { label: "Pay details", to: "/people/employee", icon: "user", hint: "Pay rate, payout details and start date for each person." },
        { label: "Expense claims", to: "/people/expense_claim", icon: "receipt", waiting: { path: "/api/minions/expense_claims", statuses: ["submitted"] } },
        { label: "Salary advances", to: "/people/salary_advance", icon: "wallet" },
        { label: "Time off", to: "/people/time_off", icon: "calendar" },
      ]],
      ["Work", [
        { label: "Staff sales", to: "/people/employee_sale", icon: "trend-up" },
        { label: "Meetings", to: "/people/meeting", icon: "calendar" },
        { label: "Open the staff app", to: "/minions/", icon: "arrow-up-right", external: true },
      ]],
    ],
  },
  web3: {
    app: "web3",
    label: "Web3",
    sections: [
      ["Money", [
        { label: "Treasury", to: "/web3/treasury", icon: "wallet" },
        { label: "Wallets", to: "/web3/wallet", icon: "key" },
        { label: "Transactions", to: "/web3/transaction", icon: "history" },
      ]],
      ["Markets", [{ label: "Market", to: "/web3/market", icon: "trend-up" }]],
    ],
  },
};

/** Which rail a URL belongs to (/etims sits under Accounting's tax). */
export function navForPath(pathname: string): AppNav | null {
  const seg = pathname.split("/")[1] ?? "";
  return APP_NAV[seg === "etims" ? "accounting" : seg] ?? null;
}

/** Where an app's screens live in the URL: Minions' admin side is People. */
export const appPath = (app: string) => (app === "minions" ? "/people" : `/${app}`);
