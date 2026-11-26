import { useEffect, useState } from "react";
import type { FieldSpec } from "../../lib/types";
import { listPeople } from "../../lib/people";
import { getReferenceLabelField, getReferenceOptions, labelForRecord } from "../../lib/referenceCache";
import { PickList, type PickOption } from "../PickList";

/** Names from one source: "app.resource" (its records' names) or
 * "people:<job>" (people with that job, as "Name (email)", so a driver's
 * Work tab still finds the vehicle by their email). A source the person
 * may not read gives none. */
async function namesFrom(source: string): Promise<string[]> {
  if (source.startsWith("people:")) {
    const job = source.slice("people:".length);
    const people = await listPeople();
    return people
      .filter((p) => p.perms.includes(job))
      .map((p) => (p.full_name ? `${p.full_name} (${p.email})` : p.email));
  }
  const [app, resource] = source.split(".");
  if (!app || !resource) return [];
  const [labelField, rows] = await Promise.all([getReferenceLabelField(app, resource), getReferenceOptions(app, resource)]);
  return rows.map((r) => labelForRecord(r, labelField));
}

/** type:"pick": a name chosen from other records (field.reference: one or
 * more comma-separated sources, see namesFrom), searchable like every other
 * picker, stored as the name itself (a vehicle's driver). A name not on
 * the list is kept as typed. */
export function PickInput({ field, value, onChange }: { field: FieldSpec; value: unknown; onChange: (v: unknown) => void }) {
  const [options, setOptions] = useState<PickOption[] | null>(null);

  useEffect(() => {
    const sources = (field.reference ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    let cancelled = false;
    Promise.all(sources.map((s) => namesFrom(s).catch(() => [] as string[]))).then((lists) => {
      if (cancelled) return;
      const names = [...new Set(lists.flat().filter(Boolean))].sort((a, b) => a.localeCompare(b));
      setOptions(names.map((n) => ({ value: n, label: n })));
    });
    return () => {
      cancelled = true;
    };
  }, [field.reference]);

  return (
    <PickList
      aria-label={field.label}
      placeholder="Search…"
      value={String(value ?? "")}
      options={options}
      onChange={onChange}
      required={field.required}
      free
    />
  );
}
