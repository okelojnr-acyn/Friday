import { useEffect, useState } from "react";
import type { FieldSpec } from "../../lib/types";
import { getReferenceLabelField, getReferenceOptions, labelForRecord } from "../../lib/referenceCache";
import { PickList, type PickOption } from "../PickList";

/** type:"pick": a name chosen from another resource's records
 * (field.reference = "app.resource"), searchable like every other picker,
 * stored as the name itself (a vehicle's driver). A name not on the list
 * is kept as typed. */
export function PickInput({ field, value, onChange }: { field: FieldSpec; value: unknown; onChange: (v: unknown) => void }) {
  const [targetApp, targetResource] = (field.reference ?? "").split(".");
  const [options, setOptions] = useState<PickOption[] | null>(null);

  useEffect(() => {
    if (!targetApp || !targetResource) return;
    let cancelled = false;
    Promise.all([getReferenceLabelField(targetApp, targetResource), getReferenceOptions(targetApp, targetResource)])
      .then(([labelField, rows]) => {
        if (cancelled) return;
        const names = [...new Set(rows.map((r) => labelForRecord(r, labelField)).filter(Boolean))];
        setOptions(names.map((n) => ({ value: n, label: n })));
      })
      .catch(() => !cancelled && setOptions([]));
    return () => {
      cancelled = true;
    };
  }, [targetApp, targetResource]);

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
