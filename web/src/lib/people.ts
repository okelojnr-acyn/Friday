import { api, LONG, SHORT } from "./api";

/** People and access (plan section 12): the kernel's /orgs/members,
 * /orgs/invites, /orgs/locations and /orgs/access/rules. */

export interface Person {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
  staff_id: string | null;
  perms: string[];
  /** Location ids; none listed = all locations. */
  locations: string[];
  reports_to: string | null;
}

export interface Invite {
  id: string;
  email: string;
  full_name: string;
  role: string;
  perms: string[];
  locations: string[];
  reports_to: string | null;
  created_at: string;
  expires_at: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  link?: string;
}

export interface Location {
  id: string;
  name: string;
  kind: "store" | "warehouse" | "office" | "other";
  address: string;
}

export interface AccessRules {
  roles: string[];
  perms: string[];
  rules: Record<string, Record<string, string>>;
}

export const listPeople = () => api.cached<Person[]>("/orgs/members", SHORT);
export const updatePerson = (
  userId: string,
  patch: { role?: string; perms?: string[]; locations?: string[]; reports_to?: string },
) => api.patch<void>(`/orgs/members/${userId}`, patch);
export const removePerson = (userId: string) => api.del<void>(`/orgs/members/${userId}`);

export const listInvites = () => api.get<Invite[]>("/orgs/invites");
export const createInvite = (body: {
  email: string;
  full_name: string;
  role: string;
  perms: string[];
  locations: string[];
  reports_to: string;
}) => api.post<Invite>("/orgs/invites", body);
export const revokeInvite = (id: string) => api.del<void>(`/orgs/invites/${id}`);

export const listLocations = () => api.cached<Location[]>("/orgs/locations", LONG);
export const saveLocation = (loc: Omit<Location, "id"> & { id?: string }) =>
  loc.id ? api.patch<Location>(`/orgs/locations/${loc.id}`, loc) : api.post<Location>("/orgs/locations", loc);

export const accessRules = () => api.cached<AccessRules>("/orgs/access/rules", LONG);

export const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  branch_manager: "Branch manager",
  team_leader: "Team leader",
  member: "Staff",
  viewer: "Viewer",
};

/** One line each, for the invite step that picks a role. */
export const ROLE_BLURB: Record<string, string> = {
  admin: "Runs the whole business from Friday, except owners, billing and Friday Host.",
  branch_manager: "Runs their stores or warehouses in Friday: sales, stock, staff there.",
  team_leader: "Leads a team on the floor from the Minions app and Guss; approves small things.",
  member: "Cashiers, floor, warehouse and drivers: their own work, through the jobs you tick.",
  viewer: "Accountants and auditors: reads what you give them, changes nothing.",
};

export const PERM_LABEL: Record<string, string> = {
  cashier: "Cashier: sells at a till",
  warehouse: "Warehouse: receives, counts and moves stock",
  logistics: "Logistics: deliveries and parcels",
  purchasing: "Purchasing: orders from suppliers",
  sales: "Sales: owns customers and deals",
  accounting: "Accounting: the books, VAT and eTIMS",
  hr: "HR: staff records and pay",
};

/** Plain words for a rule, for "what can this role do?". */
export const RULE_LABEL: Record<string, string> = {
  "pos.sell": "Sell at a till",
  "sales.read": "See sales",
  "sales.refund": "Refunds and voids",
  "invoices.read": "See invoices",
  "invoices.write": "Make invoices and pay links",
  "customers.read": "See customers and debts",
  "customers.write": "Add and edit customers",
  "crm.read": "See the sales pipeline",
  "crm.write": "Work deals",
  "stock.read": "See stock",
  "stock.write": "Receive, count and move stock",
  "purchasing.read": "See purchase orders",
  "purchasing.write": "Order from suppliers",
  "books.read": "See the books",
  "books.write": "Post to the books",
  "staff.read": "See staff",
  "pay.read": "See pay",
  "pay.write": "Change pay and pay people",
  "claims.submit": "Claim expenses",
  "claims.read": "See expense claims",
  "claims.approve": "Approve expense claims",
  "deliveries.read": "See deliveries",
  "deliveries.write": "Run deliveries",
  "settings.write": "Business settings",
  "tills.write": "Tills",
  "payment_methods.write": "Payment methods",
  "integrations.write": "Apps & integrations",
  "people.read": "See people",
  "people.write": "Invite and change people",
  "tasks.read": "See tasks",
  "tasks.assign": "Give tasks",
  "host.manage": "Friday Host: billing, servers, updates",
};

export const SCOPE_LABEL: Record<string, string> = {
  all: "everywhere",
  loc: "their locations",
  team: "their team",
  own: "their own",
};
