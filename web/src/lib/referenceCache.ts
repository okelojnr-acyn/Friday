import type { RecordRow, ResourceSpec } from "./types";
import { fetchSchema } from "./schema";
import { listRecords } from "./resourceApi";

/** Reference pickers, reference cells, and smart-button counts all need
 * "every record of the target resource" and "which field on it reads as
 * a human label" -- fetched once per resource per page load and shared,
 * instead of every field instance (a column of 50 rows, say, or a smart
 * button next to it) re-fetching the same list. resourceApi.ts
 * invalidates an entry whenever it writes that resource, so this stays
 * correct across a create/update without needing a full page reload. */

const optionsCache = new Map<string, Promise<RecordRow[]>>();
const labelFieldCache = new Map<string, Promise<string | null>>();

export function getReferenceOptions(app: string, resource: string): Promise<RecordRow[]> {
  const key = `${app}.${resource}`;
  if (!optionsCache.has(key)) {
    optionsCache.set(
      key,
      listRecords(app, resource).catch(() => []),
    );
  }
  return optionsCache.get(key)!;
}

export function invalidateReferenceOptions(app: string, resource: string): void {
  optionsCache.delete(`${app}.${resource}`);
}

function labelFieldFor(spec: ResourceSpec | undefined): string | null {
  if (!spec) return null;
  if (spec.searchFields[0]) return spec.searchFields[0];
  return spec.fields.find((f) => f.type === "text")?.name ?? null;
}

export function getReferenceLabelField(app: string, resource: string): Promise<string | null> {
  const key = `${app}.${resource}`;
  if (!labelFieldCache.has(key)) {
    labelFieldCache.set(
      key,
      fetchSchema(app)
        .then((schema) => labelFieldFor(schema.find((s) => s.name === resource)))
        .catch(() => null),
    );
  }
  return labelFieldCache.get(key)!;
}

export function labelForRecord(record: RecordRow, labelField: string | null): string {
  const raw = labelField ? record[labelField] : undefined;
  return raw ? String(raw) : record.id;
}

/** Looks up a single record's label within an already-fetched options
 * list -- resolves once options/labelField are in, settling to the raw
 * id if the referenced record was deleted. */
export async function resolveReferenceLabel(
  app: string,
  resource: string,
  id: string,
): Promise<string> {
  const [options, labelField] = await Promise.all([
    getReferenceOptions(app, resource),
    getReferenceLabelField(app, resource),
  ]);
  const record = options.find((o) => o.id === id);
  return record ? labelForRecord(record, labelField) : id;
}
