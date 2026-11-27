import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/orgSettings";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";
import { SaveRow } from "./SaveRow";

interface Policy {
  preset: "simple" | "standard" | "strict" | "custom";
  ask_first_member: number;
  ask_first_team_leader: number;
  ask_first_branch_manager: number;
  trips_ask_first: boolean;
  no_receipt_under: number;
  no_receipt_per_year: number;
  tolerance_pct: number;
  till_payouts: boolean;
  petty_float: number;
  petty_slip_max: number;
  /** Absent on an older kernel. */
  till_discount_pct?: number;
}
type Presets = Record<"simple" | "standard" | "strict", Policy>;

const PRESETS = [
  ["simple", "Simple", "A small shop: fewer questions, the till can pay small costs."],
  ["standard", "Standard", "Recommended. Common practice: receipts always, ask first for bigger spends, a separate petty cash float."],
  ["strict", "Strict", "A larger business: ask first sooner, fewer exceptions."],
] as const;

const MONEY_FIELDS = [
  ["ask_first_member", "Staff ask first above"],
  ["ask_first_team_leader", "Team leaders ask first above"],
  ["ask_first_branch_manager", "Managers ask first above"],
  ["no_receipt_under", "A written reason may replace a receipt under"],
  ["petty_float", "Petty cash float per location"],
  ["petty_slip_max", "Most paid from petty cash at once"],
] as const;

const whole = (c: number) => formatMoney(c, { whole: true });

/** Business settings > Spending: one of three ready-made policies (or
 * its numbers changed). Friday uses it for receipts, asking first, petty
 * cash and the till (Friday Host docs/SPENDING-PLAN.md). */
export function SpendingSection({ canEdit }: { canEdit: boolean }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [old, setOld] = useState(false);
  const [custom, setCustom] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<Policy & { presets: Presets }>("/orgs/spending-policy")
      .then(({ presets, ...p }) => {
        setPresets(presets);
        setPolicy(p);
        setCustom(p.preset === "custom");
      })
      .catch(() => setOld(true));
  }, []);

  async function save(next: Policy) {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const { presets: _presets, ...p } = await api.put<Policy & { presets: Presets }>("/orgs/spending-policy", next);
      setPolicy(p);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the spending policy");
    } finally {
      setSaving(false);
    }
  }

  if (old) return <div className="card card-padded">Update Friday in Friday Host to set the spending policy.</div>;
  if (!policy || !presets) return <div className="card card-padded spinner">Loading…</div>;
  const set = (patch: Partial<Policy>) => setPolicy({ ...policy, ...patch, preset: "custom" });

  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      <p className="field-label" style={{ margin: 0, maxWidth: "60ch" }}>
        How your people spend the business's money: when they ask first, when a receipt is needed, and petty cash. Pick the one that fits; you
        can change any number later.
      </p>
      <div className="spend-presets" role="radiogroup" aria-label="Spending policy">
        {PRESETS.map(([id, name, what]) => {
          const p = presets[id];
          return (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={policy.preset === id}
              disabled={!canEdit || saving}
              className={`spend-preset${policy.preset === id ? " chosen" : ""}`}
              onClick={() => {
                setCustom(false);
                void save(p);
              }}
            >
              <strong>{name}</strong>
              <span>{what}</span>
              <span className="field-label">
                Staff ask first above {whole(p.ask_first_member)}; reason instead of a receipt under {whole(p.no_receipt_under)}
                {p.till_payouts ? "; the till may pay" : ""}
              </span>
            </button>
          );
        })}
      </div>
      {policy.preset === "custom" ? <p className="field-label" style={{ margin: 0 }}>Your own numbers.</p> : null}
      {!custom ? (
        <Button variant="ghost" size="sm" onClick={() => setCustom(true)} disabled={!canEdit}>
          Change the numbers
        </Button>
      ) : (
        <>
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            {MONEY_FIELDS.map(([key, label]) => (
              <FieldWrap key={key} label={label}>
                <Input
                  inputMode="numeric"
                  disabled={!canEdit}
                  value={String(Math.round(policy[key] / 100))}
                  onChange={(e) => set({ [key]: Math.round((Number.parseFloat(e.target.value) || 0) * 100) })}
                />
              </FieldWrap>
            ))}
            <FieldWrap label="Times a person may give a reason instead of a receipt, per year">
              <Input inputMode="numeric" disabled={!canEdit} value={String(policy.no_receipt_per_year)} onChange={(e) => set({ no_receipt_per_year: Number.parseInt(e.target.value) || 0 })} />
            </FieldWrap>
            <FieldWrap label="Flag a claim over what was approved by more than (%)">
              <Input inputMode="numeric" disabled={!canEdit} value={String(policy.tolerance_pct)} onChange={(e) => set({ tolerance_pct: Number.parseInt(e.target.value) || 0 })} />
            </FieldWrap>
            {policy.till_discount_pct !== undefined ? (
              <FieldWrap
                label="Till discounts that need a manager's PIN, from (%)"
                hint="A cashier giving this much off, or lowering a price below the shelf, needs a team leader's or manager's PIN at Payment. Their name is kept on the sale. 0 means every discount asks."
              >
                <Input
                  inputMode="numeric"
                  disabled={!canEdit}
                  value={String(policy.till_discount_pct)}
                  onChange={(e) => set({ till_discount_pct: Math.min(100, Math.max(0, Number.parseInt(e.target.value) || 0)) })}
                />
              </FieldWrap>
            ) : null}
          </div>
          <label className="checkbox-row">
            <input type="checkbox" disabled={!canEdit} checked={policy.trips_ask_first} onChange={(e) => set({ trips_ask_first: e.target.checked })} />
            Trips always ask first
          </label>
          <label className="checkbox-row">
            <input type="checkbox" disabled={!canEdit} checked={policy.till_payouts} onChange={(e) => set({ till_payouts: e.target.checked })} />
            The till may pay small costs (recorded on the shift)
          </label>
          <SaveRow canEdit={canEdit} saving={saving} saved={saved} onSave={() => save(policy)} />
        </>
      )}
    </div>
  );
}
