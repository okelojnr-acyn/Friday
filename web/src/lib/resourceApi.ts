import { api, resourceBasePath } from "./api";
import type { RecordRow } from "./types";

// Every resource's update route is PATCH {base}/{id} *except* invoicing's
// invoice, which deliberately keeps status transitions separate from a
// general-purpose PATCH (apps/invoicing/app/main.py has no plain
// PATCH /invoices/{id}, only PATCH /invoices/{id}/status). The generic
// FormView still works for it -- it only needs to know the path shape.
const UPDATE_PATH_OVERRIDES: Record<string, (base: string, id: string) => string> = {
  "invoicing.invoice": (base, id) => `${base}/${id}/status`,
};

export function listRecords(app: string, resourceName: string): Promise<RecordRow[]> {
  return api.get<RecordRow[]>(resourceBasePath(app, resourceName));
}

export function createRecord(
  app: string,
  resourceName: string,
  body: Record<string, unknown>,
): Promise<RecordRow> {
  return api.post<RecordRow>(resourceBasePath(app, resourceName), body);
}

export function updateRecord(
  app: string,
  resourceName: string,
  id: string,
  body: Record<string, unknown>,
): Promise<RecordRow> {
  const base = resourceBasePath(app, resourceName);
  const override = UPDATE_PATH_OVERRIDES[`${app}.${resourceName}`];
  const path = override ? override(base, id) : `${base}/${id}`;
  return api.patch<RecordRow>(path, body);
}
