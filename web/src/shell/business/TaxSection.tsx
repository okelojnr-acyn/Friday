import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { saveOrgSettings, useOrgSettings, type TaxProfile, type TaxRate } from "../../lib/orgSettings";
import { Button } from "../../ui/Button";
import { Checkbox, FieldWrap, Input, Select, Textarea } from "../../ui/Field";
import { SaveRow } from "./SaveRow";
import { VatReturnCard } from "./VatReturnCard";

// KRA's eTIMS tax types; what an org without saved tax settings starts with.
const KENYA_RATES: TaxRate[] = [
  { code: "A", name: "Exempt", rate_bp: 0 },
  { code: "B", name: "Standard VAT", rate_bp: 1600 },
  { code: "C", name: "Zero-rated", rate_bp: 0 },
  { code: "D", name: "Non-VAT", rate_bp: 0 },
  { code: "E", name: "Reduced VAT", rate_bp: 800 },
];

const DEFAULT_PROFILE: TaxProfile = {
  vat_registered: true,
  tax_pin: "",
  default_code: "B",
  rates: KENYA_RATES,
  receipt_show_pin: true,
  receipt_show_breakdown: true,
  receipt_footer: "",
};

interface RateRow {
  code: string;
  name: string;
  pct: string;
}

/** Business settings > Tax: VAT registration and PIN, the rates the
 * business uses (coded as KRA's eTIMS tax types), which one the till
 * charges, and what the receipt prints. */
export function TaxSection({ canEdit }: { canEdit: boolean }) {
  const settings = useOrgSettings();
  const kenya = settings.currency === "KES";
  const [p, setP] = useState<TaxProfile>(settings.tax ?? DEFAULT_PROFILE);
  const [rates, setRates] = useState<RateRow[]>(toRows((settings.tax ?? DEFAULT_PROFILE).rates));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = settings.tax ?? DEFAULT_PROFILE;
    setP(t);
    setRates(toRows(t.rates));
  }, [settings]);

  const set = <K extends keyof TaxProfile>(k: K, v: TaxProfile[K]) => setP((x) => ({ ...x, [k]: v }));
  const setRate = (i: number, patch: Partial<RateRow>) => setRates((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function save() {
    setError(null);
    const parsed: TaxRate[] = [];
    for (const r of rates) {
      const pct = Number.parseFloat(r.pct);
      if (!Number.isFinite(pct) || pct < 0 || pct > 50) {
        setError(`Rate ${r.code || "?"}: the percentage must be between 0 and 50.`);
        return;
      }
      parsed.push({ code: r.code.trim().toUpperCase(), name: r.name.trim(), rate_bp: Math.round(pct * 100) });
    }
    setSaving(true);
    try {
      await saveOrgSettings({ tax: { ...p, rates: parsed } });
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setSaving(false);
    }
  }

  const tillRate = rates.find((r) => r.code.trim().toUpperCase() === p.default_code);
  return (
    <>
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}

      <h2 style={{ fontSize: 18, margin: 0 }}>Registration</h2>
      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Checkbox checked={p.vat_registered} onChange={(e) => set("vat_registered", e.target.checked)} disabled={!canEdit} />
        Registered for VAT
      </label>
      <FieldWrap label={kenya ? "KRA PIN" : "Tax ID"} required={p.vat_registered}>
        <Input
          name="business-tax-pin"
          autoComplete="off"
          placeholder={kenya ? "P051234567X" : ""}
          value={p.tax_pin}
          onChange={(e) => set("tax_pin", e.target.value.toUpperCase())}
          disabled={!canEdit}
          style={{ width: 220, fontFamily: "var(--font-mono, monospace)" }}
        />
      </FieldWrap>

      <h2 style={{ fontSize: 18, margin: "8px 0 0" }}>Rates</h2>
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        Codes A to E are KRA's eTIMS tax types; eTIMS reports each sale under its code.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {rates.map((r, i) => (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Input
              aria-label="Code"
              name={`tax-code-${i}`}
              autoComplete="off"
              value={r.code}
              maxLength={4}
              onChange={(e) => setRate(i, { code: e.target.value.toUpperCase() })}
              disabled={!canEdit}
              style={{ width: 64 }}
            />
            <Input
              aria-label="Name"
              name={`tax-name-${i}`}
              autoComplete="off"
              value={r.name}
              maxLength={40}
              onChange={(e) => setRate(i, { name: e.target.value })}
              disabled={!canEdit}
              style={{ flex: "1 1 160px", minWidth: 0 }}
            />
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Input
                aria-label="Percent"
                inputMode="decimal"
                value={r.pct}
                onChange={(e) => setRate(i, { pct: e.target.value })}
                disabled={!canEdit}
                style={{ width: 80 }}
              />
              %
            </span>
            {canEdit && rates.length > 1 ? (
              <Button size="sm" onClick={() => setRates((rs) => rs.filter((_, j) => j !== i))} aria-label={`Remove rate ${r.code}`}>
                Remove
              </Button>
            ) : null}
          </div>
        ))}
        {canEdit && rates.length < 20 ? (
          <div>
            <Button size="sm" onClick={() => setRates((rs) => [...rs, { code: "", name: "", pct: "0" }])}>
              Add a rate
            </Button>
          </div>
        ) : null}
      </div>
      <FieldWrap label="The till charges">
        <Select value={p.default_code} onChange={(e) => set("default_code", e.target.value)} disabled={!canEdit}>
          {rates
            .filter((r) => r.code.trim())
            .map((r) => (
              <option key={r.code} value={r.code.trim().toUpperCase()}>
                {r.code.trim().toUpperCase()} · {r.name} ({r.pct}%)
              </option>
            ))}
        </Select>
      </FieldWrap>
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        {p.vat_registered
          ? `Every sale is taxed at ${tillRate ? `${tillRate.pct}%` : "the chosen rate"}${settings.prices_include_tax ? ", inside the shelf price" : ", added at the till"}.`
          : "Not registered for VAT: the till charges no VAT."}
      </p>

      <h2 style={{ fontSize: 18, margin: "8px 0 0" }}>Receipt</h2>
      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Checkbox checked={p.receipt_show_pin} onChange={(e) => set("receipt_show_pin", e.target.checked)} disabled={!canEdit} />
        Print the {kenya ? "KRA PIN" : "tax ID"} on receipts
      </label>
      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Checkbox
          checked={p.receipt_show_breakdown}
          onChange={(e) => set("receipt_show_breakdown", e.target.checked)}
          disabled={!canEdit}
        />
        Print the VAT amount on receipts
      </label>
      <FieldWrap label="Address on receipts">
        <Input
          name="receipt-address"
          autoComplete="street-address"
          maxLength={120}
          placeholder="Shop 4, Westlands Mall, Nairobi"
          value={p.receipt_address ?? ""}
          onChange={(e) => set("receipt_address", e.target.value)}
          disabled={!canEdit}
        />
      </FieldWrap>
      <FieldWrap label="Phone on receipts">
        <Input
          name="receipt-phone"
          autoComplete="tel"
          maxLength={40}
          placeholder="0712 345 678"
          value={p.receipt_phone ?? ""}
          onChange={(e) => set("receipt_phone", e.target.value)}
          disabled={!canEdit}
          style={{ width: 220 }}
        />
      </FieldWrap>
      <FieldWrap label="Receipt footer">
        <Textarea
          rows={2}
          maxLength={200}
          placeholder="Thank you"
          value={p.receipt_footer}
          onChange={(e) => set("receipt_footer", e.target.value)}
          disabled={!canEdit}
        />
      </FieldWrap>
      <SaveRow canEdit={canEdit} saving={saving} onSave={save} />
    </div>
    {canEdit ? <VatReturnCard /> : null}
    </>
  );
}

function toRows(rates: TaxRate[]): RateRow[] {
  return rates.map((r) => ({ code: r.code, name: r.name, pct: String(r.rate_bp / 100) }));
}
