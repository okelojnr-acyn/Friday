import { useEffect, useMemo, useState } from "react";
import type { FieldSpec, RecordRow } from "../../lib/types";
import { getReferenceLabelField, getReferenceOptions, labelForRecord } from "../../lib/referenceCache";
import { Input } from "../Field";

interface ReferenceInputProps {
  field: FieldSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}

/** The real control for type:"reference" fields -- a searchable picker
 * over the target resource (field.reference = "app.resource"), storing
 * the picked record's id. Without this, a reference field is just a
 * text box the user has to type a raw UUID into. */
export function ReferenceInput({ field, value, onChange }: ReferenceInputProps) {
  const [targetApp, targetResource] = (field.reference ?? "").split(".");
  const [options, setOptions] = useState<RecordRow[] | null>(null);
  const [labelField, setLabelField] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!targetApp || !targetResource) return;
    let cancelled = false;
    getReferenceLabelField(targetApp, targetResource).then((f) => !cancelled && setLabelField(f));
    getReferenceOptions(targetApp, targetResource).then((rows) => !cancelled && setOptions(rows));
    return () => {
      cancelled = true;
    };
  }, [targetApp, targetResource]);

  const selected = useMemo(() => options?.find((o) => o.id === value) ?? null, [options, value]);

  const filtered = useMemo(() => {
    if (!options) return [];
    const q = query.trim().toLowerCase();
    if (!q) return options.slice(0, 20);
    return options.filter((o) => labelForRecord(o, labelField).toLowerCase().includes(q)).slice(0, 20);
  }, [options, query, labelField]);

  if (!targetApp || !targetResource) {
    return <Input type="text" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }

  return (
    <div className="ref-picker">
      <Input
        type="text"
        placeholder={options === null ? "Loading..." : `Search ${targetResource}...`}
        value={open ? query : selected ? labelForRecord(selected, labelField) : ""}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        required={field.required}
      />
      {open && options !== null ? (
        <div className="ref-picker-results">
          {filtered.length === 0 ? (
            <div className="ref-picker-empty">No matches</div>
          ) : (
            filtered.map((o) => (
              <button
                key={o.id}
                type="button"
                className="ref-picker-row"
                onMouseDown={() => {
                  onChange(o.id);
                  setOpen(false);
                }}
              >
                {labelForRecord(o, labelField)}
              </button>
            ))
          )}
        </div>
      ) : null}
      {selected && !field.required ? (
        <button type="button" className="ref-picker-clear" onClick={() => onChange(null)}>
          Clear
        </button>
      ) : null}
    </div>
  );
}
