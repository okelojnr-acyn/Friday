import { api, resourceBasePath } from "./api";
import type { RecordRow } from "./types";
import { invalidateReferenceOptions } from "./referenceCache";

// Every resource's update route is PATCH {base}/{id} *except* invoicing's
// invoice, which deliberately keeps status transitions separate from a
// general-purpose PATCH (apps/invoicing/app/main.py has no plain
// PATCH /invoices/{id}, only PATCH /invoices/{id}/status). The generic
// FormView still works for it -- it only needs to know the path shape.
const UPDATE_PATH_OVERRIDES: Record<string, (base: string, id: string) => string> = {
  "invoicing.invoice": (base, id) => `${base}/${id}/status`,
  "invoicing.quote": (base, id) => `${base}/${id}/status`,
  "inventory.purchase_order": (base, id) => `${base}/${id}/status`,
};

export function listRecords(app: string, resourceName: string): Promise<RecordRow[]> {
  return api.get<RecordRow[]>(resourceBasePath(app, resourceName));
}

export async function createRecord(
  app: string,
  resourceName: string,
  body: Record<string, unknown>,
): Promise<RecordRow> {
  const created = await api.post<RecordRow>(resourceBasePath(app, resourceName), body);
  invalidateReferenceOptions(app, resourceName);
  return created;
}

export async function updateRecord(
  app: string,
  resourceName: string,
  id: string,
  body: Record<string, unknown>,
): Promise<RecordRow> {
  const base = resourceBasePath(app, resourceName);
  const override = UPDATE_PATH_OVERRIDES[`${app}.${resourceName}`];
  const path = override ? override(base, id) : `${base}/${id}`;
  const updated = await api.patch<RecordRow>(path, body);
  invalidateReferenceOptions(app, resourceName);
  return updated;
}
