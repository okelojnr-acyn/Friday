import { useId, useMemo, useState } from "react";
import { Input } from "./Field";

export interface PickOption {
  value: string;
  label: string;
  /** A second, quieter line: a role, an SKU, a price. */
  hint?: string;
}

interface PickListProps {
  options: PickOption[] | null;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  "aria-label"?: string;
  /** Keep whatever is typed (a new product name, say) as the value. */
  free?: boolean;
}

/** A searchable dropdown: type to narrow, tap or arrow+Enter to pick.
 * Its list is never narrower than 240px, so long names stay readable
 * inside tight rows (order and invoice lines). */
export function PickList({ options, value, onChange, placeholder, required, free, ...rest }: PickListProps) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const selected = options?.find((o) => o.value === value) ?? null;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = options ?? [];
    return (q ? all.filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(q)) : all).slice(0, 50);
  }, [options, query]);

  function pick(o: PickOption) {
    onChange(o.value);
    setQuery("");
    setOpen(false);
  }

  return (
    <div className="ref-picker">
      <Input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-label={rest["aria-label"]}
        autoComplete="off"
        placeholder={options === null ? "Loading…" : (placeholder ?? "Search…")}
        value={open ? query : (selected?.label ?? (free ? value : ""))}
        required={required}
        onFocus={() => {
          setQuery(free && !selected ? value : "");
          setActive(0);
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
          if (free) onChange(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          else if (e.key === "ArrowDown") (e.preventDefault(), setOpen(true), setActive((a) => Math.min(a + 1, shown.length - 1)));
          else if (e.key === "ArrowUp") (e.preventDefault(), setActive((a) => Math.max(a - 1, 0)));
          else if (e.key === "Enter" && open && shown[active]) (e.preventDefault(), pick(shown[active]));
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && options !== null ? (
        <div className="ref-picker-results" id={`${id}-list`} role="listbox">
          {shown.length === 0 ? (
            <div className="ref-picker-empty">{free && query.trim() ? `“${query.trim()}” will be used as typed` : "No matches"}</div>
          ) : (
            shown.map((o, i) => (
              <button
                key={o.value}
                type="button"
                role="option"
                aria-selected={o.value === value}
                className={`ref-picker-row${i === active ? " active" : ""}`}
                onMouseDown={(e) => (e.preventDefault(), pick(o))}
              >
                {o.label}
                {o.hint ? <span className="ref-picker-hint">{o.hint}</span> : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
