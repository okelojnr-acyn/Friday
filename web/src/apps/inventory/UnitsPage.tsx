import { useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { CATEGORY_LABEL, createUnit, fmtQty, patchUnit, useUnits, type Unit } from "../../lib/units";
import { Button } from "../../ui/Button";
import { FieldWrap, Input, Select } from "../../ui/Field";

/** Inventory > Units of measure. The standard set comes preloaded; bench
 * the ones the business never uses so they leave the pickers. A unit a
 * product uses can't be benched. */
export function UnitsPage() {
  const { session } = useAuth();
  const canEdit = session?.role === "owner" || session?.role === "admin";
  const { units, reload } = useUnits();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", abbreviation: "", category: "unit", pack: true, ratio: "", etims_code: "" });

  async function toggle(u: Unit) {
    setBusy(u.id);
    setError(null);
    try {
      await patchUnit(u.id, { active: !u.active });
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(null);
    }
  }

  async function add() {
    setError(null);
    const ratio = form.pack ? null : Number.parseFloat(form.ratio);
    if (!form.pack && !(ratio && ratio > 0)) {
      setError("Give the unit's size, e.g. 0.5 for half a kilogram.");
      return;
    }
    setBusy("new");
    try {
      await createUnit({ name: form.name.trim(), abbreviation: form.abbreviation.trim(), category: form.category, ratio, etims_code: form.etims_code });
      setForm({ name: "", abbreviation: "", category: "unit", pack: true, ratio: "", etims_code: "" });
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the unit.");
    } finally {
      setBusy(null);
    }
  }

  const groups = Object.keys(CATEGORY_LABEL) as Unit["category"][];
  const reference: Record<Unit["category"], string> = { unit: "piece", weight: "kg", volume: "L", length: "m", area: "m²", time: "hour" };
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <div className="page-header">
        <h1 className="page-title">Units of measure</h1>
      </div>
      <p className="field-label" style={{ maxWidth: "65ch", marginTop: 0 }}>
        Each product keeps stock in one base unit, is bought in a purchase unit and sold in a sales unit. Units in the
        same group convert by themselves (1 kg = 1000 g). A pack (carton, crate, sack) has its size set on each product.
      </p>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      {groups.map((g) => {
        const list = units.filter((u) => u.category === g);
        if (!list.length) return null;
        return (
          <div key={g} className="card card-padded" style={{ marginBottom: 12 }}>
            <h2 style={{ fontSize: 17, margin: "0 0 8px" }}>{CATEGORY_LABEL[g]}</h2>
            {list.map((u) => (
              <div
                key={u.id}
                style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", alignItems: "center", padding: "6px 0", borderTop: "1px solid var(--border)", opacity: u.active ? 1 : 0.55 }}
              >
                <span style={{ flex: "1 1 180px", minWidth: 0 }}>
                  <strong>{u.name}</strong> <span className="field-label">{u.abbreviation}</span>
                </span>
                <span className="field-label" style={{ flex: "0 1 170px" }}>
                  {u.ratio == null ? "pack: size per product" : `= ${fmtQty(u.ratio)} ${reference[g]}`}
                </span>
                <span className="field-label" style={{ flex: "0 1 90px", fontFamily: "var(--font-mono, monospace)" }}>
                  {u.etims_code ? `KRA ${u.etims_code}` : ""}
                </span>
                <span className="field-label" style={{ flex: "0 1 110px" }}>
                  {u.products_using ? `${u.products_using} product${u.products_using === 1 ? "" : "s"}` : ""}
                </span>
                {canEdit ? (
                  <Button size="sm" disabled={busy === u.id || (u.active && u.products_using > 0)} onClick={() => toggle(u)}>
                    {u.active ? "Bench" : "Use again"}
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        );
      })}
      {canEdit ? (
        <div className="card card-padded form-grid">
          <h2 style={{ fontSize: 17, margin: 0 }}>Add a unit</h2>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <FieldWrap label="Name" required>
              <Input name="unit-name" autoComplete="off" value={form.name} maxLength={40} placeholder="Bale" onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </FieldWrap>
            <FieldWrap label="Symbol">
              <Input name="unit-symbol" autoComplete="off" value={form.abbreviation} maxLength={10} placeholder="bl" onChange={(e) => setForm({ ...form, abbreviation: e.target.value })} style={{ width: 90 }} />
            </FieldWrap>
            <FieldWrap label="Group">
              <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value, pack: e.target.value === "unit" ? form.pack : false })}>
                {groups.map((g) => (
                  <option key={g} value={g}>
                    {CATEGORY_LABEL[g]}
                  </option>
                ))}
              </Select>
            </FieldWrap>
            {form.category === "unit" ? (
              <FieldWrap label="Kind">
                <Select value={form.pack ? "pack" : "fixed"} onChange={(e) => setForm({ ...form, pack: e.target.value === "pack" })}>
                  <option value="pack">Pack: size per product</option>
                  <option value="fixed">Fixed number of pieces</option>
                </Select>
              </FieldWrap>
            ) : null}
            {!form.pack ? (
              <FieldWrap label={`Size in ${reference[form.category as Unit["category"]]}`}>
                <Input inputMode="decimal" value={form.ratio} onChange={(e) => setForm({ ...form, ratio: e.target.value })} style={{ width: 110 }} />
              </FieldWrap>
            ) : null}
            <FieldWrap label="KRA unit code">
              <Input name="unit-kra" autoComplete="off" value={form.etims_code} maxLength={5} placeholder="optional" onChange={(e) => setForm({ ...form, etims_code: e.target.value.toUpperCase() })} style={{ width: 100 }} />
            </FieldWrap>
            <Button variant="primary" disabled={!form.name.trim() || busy === "new"} onClick={add}>
              Add unit
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
