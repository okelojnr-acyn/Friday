// Mirrors packages/py-common/friday_common/resource.py's `to_json()`
// output exactly. This is the schema-driven UI contract: every app
// exposes GET /schema returning ResourceSpec[], and web/src/ui/resource
// turns that directly into list/kanban/form screens.

export type FieldType =
  | "text"
  | "textarea"
  | "number"
  | "currency"
  | "boolean"
  | "date"
  | "datetime"
  | "select"
  | "reference"
  | "email"
  | "phone";

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  options: string[] | null;
  reference: string | null;
  listVisible: boolean;
  formVisible: boolean;
}

export type ViewKind = "list" | "kanban" | "form";

export interface ResourceSpec {
  name: string;
  app: string;
  label: string;
  labelPlural: string;
  views: ViewKind[];
  kanbanGroupBy: string | null;
  searchFields: string[];
  fields: FieldSpec[];
}

export interface AppCatalogEntry {
  name: string;
  label: string;
  description: string;
  icon: string;
  category: string;
  installed: boolean;
}

export interface Session {
  token: string;
  orgId: string;
  role: "owner" | "admin" | "member" | "viewer";
  email: string;
}

// Any resource record: every record carries at least an id, plus
// whatever fields its ResourceSpec declares.
export type RecordRow = Record<string, unknown> & { id: string };
