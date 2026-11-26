import { useEffect, useMemo, useState } from "react";
import type { FieldSpec, RecordRow } from "../../lib/types";
import { getReferenceLabelField, getReferenceOptions, labelForRecord } from "../../lib/referenceCache";
import { createRecord } from "../../lib/resourceApi";
import { api, ApiError } from "../../lib/api";
import { listPeople } from "../../lib/people";
import { PickList, type PickOption } from "../PickList";
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
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

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

  // Not in the list? Add it right here (the Xero/QuickBooks pattern), so a
  // new customer doesn't mean leaving the invoice. An email typed for a
  // customer becomes their email, its name part their name.
  async function addNew() {
    const q = query.trim();
    if (!q || !labelField) return;
    const body: Record<string, unknown> = { [labelField]: q };
    if (targetResource === "customer" && q.includes("@")) {
      body.email = q;
      if (labelField !== "email") body[labelField] = q.split("@")[0];
    }
    setAdding(true);
    setAddError(null);
    try {
      const row = await createRecord(targetApp, targetResource, body);
      setOptions((cur) => [row, ...(cur ?? [])]);
      onChange(row.id);
      setOpen(false);
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : `Could not add this ${targetResource}`);
    } finally {
      setAdding(false);
    }
  }

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
          {query.trim() && labelField && !filtered.some((o) => labelForRecord(o, labelField).toLowerCase() === query.trim().toLowerCase()) ? (
            <button type="button" className="ref-picker-row ref-picker-add" disabled={adding} onMouseDown={(e) => (e.preventDefault(), addNew())}>
              {adding ? "Adding…" : `+ Add “${query.trim()}” as a new ${targetResource.replace(/_/g, " ")}`}
            </button>
          ) : null}
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
      {addError ? <div className="error-banner" role="alert" style={{ marginTop: 6 }}>{addError}</div> : null}
      {selected && !field.required ? (
        <button type="button" className="ref-picker-clear" onClick={() => onChange(null)}>
          Clear
        </button>
      ) : null}
    </div>
  );
}

/** type:"person" fields: someone in the business, stored by email, from
 * a searchable list of whom I may pick (field.reference: an API path
 * answering {anyone, user_ids}). */
export function PersonInput({ field, value, onChange }: ReferenceInputProps) {
  const [options, setOptions] = useState<PickOption[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listPeople(),
      field.reference ? api.get<{ anyone: boolean; user_ids: string[] }>(field.reference).catch(() => null) : null,
    ])
      .then(([people, allowed]) => {
        const ok = allowed && !allowed.anyone ? new Set(allowed.user_ids) : null;
        const rows = people
          .filter((p) => !ok || ok.has(p.user_id))
          .map((p) => ({ value: p.email, label: p.full_name || p.email, hint: p.role.replace(/_/g, " ") }))
          .sort((a, b) => a.label.localeCompare(b.label));
        if (!cancelled) setOptions(rows);
      })
      .catch(() => !cancelled && setOptions([]));
    return () => {
      cancelled = true;
    };
  }, [field.reference]);
  return (
    <PickList
      options={options}
      value={(value as string) ?? ""}
      onChange={onChange}
      placeholder={`Search people…`}
      required={field.required}
      aria-label={field.label}
    />
  );
}
