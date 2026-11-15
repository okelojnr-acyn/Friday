import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { formatMoney, saveOrgSettings, useOrgSettings } from "../lib/orgSettings";
import { Button } from "../ui/Button";
import { Checkbox, FieldWrap, Input, Select } from "../ui/Field";

const CURRENCIES = [
  ["KES", "Kenyan shilling"],
  ["UGX", "Ugandan shilling"],
  ["TZS", "Tanzanian shilling"],
  ["RWF", "Rwandan franc"],
  ["ETB", "Ethiopian birr"],
  ["NGN", "Nigerian naira"],
  ["GHS", "Ghanaian cedi"],
  ["ZAR", "South African rand"],
  ["USD", "US dollar"],
  ["EUR", "Euro"],
  ["GBP", "British pound"],
] as const;

/** Settings > Business: the currency every amount is shown in, and how
 * tax works at the till (kernel /orgs/settings). */
export function BusinessSettingsPage() {
  const { session } = useAuth();
  const settings = useOrgSettings();
  const canEdit = session?.role === "owner" || session?.role === "admin";
  const [currency, setCurrency] = useState(settings.currency);
  const [rate, setRate] = useState(String(settings.tax_rate_bp / 100));
  const [inclusive, setInclusive] = useState(settings.prices_include_tax);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrency(settings.currency);
    setRate(String(settings.tax_rate_bp / 100));
    setInclusive(settings.prices_include_tax);
  }, [settings]);

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    const pct = Number.parseFloat(rate);
    if (!Number.isFinite(pct) || pct < 0 || pct > 50) {
      setError("Tax rate must be between 0 and 50%.");
      setSaving(false);
      return;
    }
    try {
      await saveOrgSettings({ currency, tax_rate_bp: Math.round(pct * 100), prices_include_tax: inclusive });
      // Every screen reads these once; reload so all of them pick it up.
      window.location.reload();
      setNotice("Saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  const example = 116000;
  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <div className="page-header">
        <h1 className="page-title">Business settings</h1>
      </div>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      {notice ? <div className="field-label" style={{ marginBottom: 16 }}>{notice}</div> : null}
      <div className="card card-padded form-grid">
        <FieldWrap label="Currency">
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)} disabled={!canEdit}>
            {CURRENCIES.map(([code, label]) => (
              <option key={code} value={code}>
                {code} · {label}
              </option>
            ))}
            {CURRENCIES.some(([c]) => c === currency) ? null : <option value={currency}>{currency}</option>}
          </Select>
        </FieldWrap>
        <FieldWrap label="VAT / sales tax (%)">
          <Input
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            disabled={!canEdit}
            style={{ width: 120 }}
          />
        </FieldWrap>
        <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Checkbox checked={inclusive} onChange={(e) => setInclusive(e.target.checked)} disabled={!canEdit} />
          Shelf prices already include VAT
        </label>
        <p className="field-label" style={{ maxWidth: "60ch" }}>
          {inclusive
            ? `An item priced ${formatMoney(example, { currency })} costs the customer exactly that; the receipt shows the VAT inside it.`
            : `An item priced ${formatMoney(example, { currency })} costs the customer that plus VAT at the till.`}
        </p>
        {canEdit ? (
          <div>
            <Button variant="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        ) : (
          <p className="field-label">Only owners and admins can change these.</p>
        )}
      </div>
    </div>
  );
}
