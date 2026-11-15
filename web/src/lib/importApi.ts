import { api } from "./api";

/** Settings > Import (plan 2.4). Targets come from each app
 * (friday_common/importer.py); an old database is read through the
 * kernel (kernel/internal/importsource). */

export type ImportFieldKind = "text" | "email" | "phone" | "cents" | "int" | "bool";

export interface ImportField {
  name: string;
  label: string;
  kind: ImportFieldKind;
  required: boolean;
}

export interface ImportTarget {
  app: string;
  entity: string;
  label: string;
  fields: ImportField[];
}

export interface ImportResult {
  inserted: number;
  updated: number;
  errors: { external_id: string; message: string }[];
}

export interface SourceTable {
  name: string;
  columns: { name: string; type: string }[];
  estimated_rows: number;
}

export interface SourceRow {
  key: string;
  values: Record<string, unknown>;
}

/** Apps that offer imports today. An app that isn't installed (or is
 * down) is skipped rather than failing the page. */
const IMPORT_APPS = ["invoicing", "inventory"];

export async function listImportTargets(): Promise<ImportTarget[]> {
  const lists = await Promise.all(
    IMPORT_APPS.map((app) =>
      api
        .get<Omit<ImportTarget, "app">[]>(`/api/${app}/import/targets`)
        .then((ts) => ts.map((t) => ({ ...t, app })))
        .catch(() => [] as ImportTarget[]),
    ),
  );
  return lists.flat();
}

export function importRows(
  target: ImportTarget,
  source: string,
  rows: { external_id: string; values: Record<string, unknown> }[],
): Promise<ImportResult> {
  return api.post<ImportResult>(`/api/${target.app}/import/${target.entity}`, { source, rows });
}

export function listSourceTables(url: string): Promise<{ tables: SourceTable[] }> {
  return api.post("/orgs/import/source", { url });
}

export function readSourceRows(
  url: string,
  table: string,
  key: string,
  after: string | null,
  limit: number,
): Promise<{ rows: SourceRow[]; next: string | null }> {
  return api.post("/orgs/import/source", { url, table, key, after, limit });
}
