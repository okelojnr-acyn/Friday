import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { formatMoney, saveOrgSettings, useOrgSettings } from "../lib/orgSettings";
import { Button } from "../ui/Button";
import { Checkbox, FieldWrap, Select } from "../ui/Field";
import { ApprovalsSection } from "./business/ApprovalsSection";
import { SpendingSection } from "./business/SpendingSection";
import { EtimsSection } from "./business/EtimsSection";
import { PaymentsSection } from "./business/PaymentsSection";
import { SaveRow, reloadSaved } from "./business/SaveRow";
import { ShopSection } from "./business/ShopSection";
import { TaxSection } from "./business/TaxSection";
import { TillsSection } from "./business/TillsSection";

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

// Every zone the browser knows; a short list if it can't say.
const ZONES: string[] = (() => {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["Africa/Nairobi", "Africa/Kampala", "Africa/Dar_es_Salaam", "Africa/Kigali", "Africa/Lagos", "UTC"];
  }
})();

const TABS = [
  ["general", "General"],
  ["tax", "Tax"],
  ["etims", "eTIMS"],
  ["tills", "Tills"],
  ["payments", "Payments"],
  ["approvals", "Approvals"],
  ["spending", "Spending"],
  ["shop", "Online shop"],
] as const;
type Tab = (typeof TABS)[number][0];

/** Settings > Business: currency and shelf prices (General), VAT and
 * receipts (Tax), KRA eTIMS, the tills a POS can be (Tills), and the
 * payment methods the business and each till take (Payments). */
export function BusinessSettingsPage() {
  const { session } = useAuth();
  const canEdit = session?.role === "owner" || session?.role === "admin";
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = TABS.some(([id]) => id === raw) ? (raw as Tab) : "general";

  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <div className="page-header">
        <h1 className="page-title">Business settings</h1>
      </div>
      <div role="tablist" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        {TABS.map(([id, label]) => (
          <Button
            key={id}
            role="tab"
            aria-selected={tab === id}
            variant={tab === id ? "primary" : "secondary"}
            size="sm"
            onClick={() => setParams(id === "general" ? {} : { tab: id }, { replace: true })}
          >
            {label}
          </Button>
        ))}
      </div>
      {tab === "general" ? <GeneralSection canEdit={canEdit} /> : null}
      {tab === "tax" ? <TaxSection canEdit={canEdit} /> : null}
      {tab === "etims" ? <EtimsSection canEdit={canEdit} /> : null}
      {tab === "tills" ? <TillsSection canEdit={canEdit} /> : null}
      {tab === "payments" ? <PaymentsSection canEdit={canEdit} /> : null}
      {tab === "approvals" ? <ApprovalsSection canEdit={canEdit} /> : null}
      {tab === "spending" ? <SpendingSection canEdit={canEdit} /> : null}
      {tab === "shop" ? <ShopSection canEdit={canEdit} /> : null}
    </div>
  );
}

function GeneralSection({ canEdit }: { canEdit: boolean }) {
  const settings = useOrgSettings();
  const [currency, setCurrency] = useState(settings.currency);
  const [inclusive, setInclusive] = useState(settings.prices_include_tax);
  const [timeZone, setTimeZone] = useState(settings.time_zone ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrency(settings.currency);
    setInclusive(settings.prices_include_tax);
    setTimeZone(settings.time_zone ?? "");
  }, [settings]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveOrgSettings({
        currency,
        prices_include_tax: inclusive,
        ...(timeZone && timeZone !== settings.time_zone ? { time_zone: timeZone } : {}),
      });
      // Every screen reads these once; reload so all of them pick it up.
      reloadSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setSaving(false);
    }
  }

  const example = 116000;
  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      <FieldWrap label="Currency" hint="The money your prices, invoices and books are in. Changing it doesn't convert amounts already recorded.">
        <Select value={currency} onChange={(e) => setCurrency(e.target.value)} disabled={!canEdit}>
          {CURRENCIES.map(([code, label]) => (
            <option key={code} value={code}>
              {code} · {label}
            </option>
          ))}
          {CURRENCIES.some(([c]) => c === currency) ? null : <option value={currency}>{currency}</option>}
        </Select>
      </FieldWrap>
      {settings.suggested_currency && settings.suggested_currency !== currency && canEdit ? (
        <p className="field-label" style={{ margin: 0 }}>
          Most businesses in {settings.time_zone} use {settings.suggested_currency}.{" "}
          <Button size="sm" variant="ghost" onClick={() => setCurrency(settings.suggested_currency!)}>
            Use {settings.suggested_currency}
          </Button>
        </p>
      ) : null}
      {settings.time_zone !== undefined ? (
        <FieldWrap label="Time zone" hint="When the business's day starts and ends: daily sales, reports and the books' dates follow it.">
          <Select value={timeZone} onChange={(e) => setTimeZone(e.target.value)} disabled={!canEdit}>
            {timeZone ? null : <option value="">Not set (UTC)</option>}
            {ZONES.map((z) => (
              <option key={z} value={z}>
                {z.replace(/_/g, " ")}
              </option>
            ))}
            {!timeZone || ZONES.includes(timeZone) ? null : <option value={timeZone}>{timeZone}</option>}
          </Select>
        </FieldWrap>
      ) : null}
      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Checkbox checked={inclusive} onChange={(e) => setInclusive(e.target.checked)} disabled={!canEdit} />
        Shelf prices already include VAT
      </label>
      <p className="field-label" style={{ maxWidth: "60ch" }}>
        {inclusive
          ? `An item priced ${formatMoney(example, { currency })} costs the customer exactly that; the receipt shows the VAT inside it.`
          : `An item priced ${formatMoney(example, { currency })} costs the customer that plus VAT at the till.`}
      </p>
      <SaveRow canEdit={canEdit} saving={saving} onSave={save} />
    </div>
  );
}
