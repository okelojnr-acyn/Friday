import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { listIntegrations } from "../../lib/integrations";
import { saveOrgSettings, useOrgSettings } from "../../lib/orgSettings";
import { PAYMENT_METHODS, PAYMENT_METHOD_LABEL } from "../../lib/pos";
import { listRegisters, updateRegister, type PosRegister } from "../../lib/posApi";
import { Checkbox } from "../../ui/Field";
import { SaveRow } from "./SaveRow";

const GATEWAYS = ["paystack", "pesapal"];

/** Business settings > Payments: what the business takes, and any till
 * that takes less (plan 15.3). The till and invoice pay links offer only
 * what's on; Paystack and Pesapal also need connecting in Integrations. */
export function PaymentsSection({ canEdit }: { canEdit: boolean }) {
  const settings = useOrgSettings();
  // An older kernel has no payment_methods yet: everything stays on.
  const kernelReady = settings.payment_methods !== undefined;
  const [methods, setMethods] = useState<string[]>(settings.payment_methods ?? PAYMENT_METHODS);
  const [regs, setRegs] = useState<PosRegister[] | null>(null);
  const [connected, setConnected] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setMethods(settings.payment_methods ?? PAYMENT_METHODS), [settings]);
  useEffect(() => {
    listRegisters()
      .then(setRegs)
      .catch(() => setRegs([]));
    listIntegrations()
      .then((rows) => setConnected(rows.map((r) => r.provider)))
      .catch(() => {});
  }, []);

  function toggle(list: string[], m: string): string[] {
    return list.includes(m) ? list.filter((x) => x !== m) : PAYMENT_METHODS.filter((x) => x === m || list.includes(x));
  }

  async function saveBusiness() {
    if (methods.length === 0) return setError("Keep at least one payment method.");
    setSaving(true);
    setError(null);
    try {
      await saveOrgSettings({ payment_methods: methods });
      // The till reads these once; reload so it picks them up.
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setSaving(false);
    }
  }

  async function saveTill(r: PosRegister, next: string[] | null) {
    setError(null);
    try {
      const saved = await updateRegister(r.id, { payment_methods: next });
      setRegs((rs) => rs?.map((x) => (x.id === r.id ? { ...x, payment_methods: saved.payment_methods ?? null } : x)) ?? rs);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the till.");
    }
  }

  function boxes(list: string[], onToggle: (m: string) => void, disabled: boolean) {
    return (
      <div style={{ display: "grid", gap: 6 }}>
        {PAYMENT_METHODS.map((m) => (
          <label key={m} style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Checkbox checked={list.includes(m)} onChange={() => onToggle(m)} disabled={disabled} />
            {PAYMENT_METHOD_LABEL[m]}
            {GATEWAYS.includes(m) && !connected.includes(m) ? (
              <span className="field-label">· connect it in Settings › Integrations first</span>
            ) : null}
          </label>
        ))}
      </div>
    );
  }

  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        What the business takes. The till offers only these, and invoices get a Paystack pay link when Paystack is on.
        A Paystack or Pesapal payment counts only once the provider confirms it.
      </p>
      {boxes(methods, (m) => setMethods((l) => toggle(l, m)), !canEdit || !kernelReady)}
      {kernelReady ? (
        <SaveRow canEdit={canEdit} saving={saving} onSave={saveBusiness} />
      ) : (
        <p className="field-label">Update Friday in Friday Host to choose the business's payment methods.</p>
      )}

      {regs && regs.length > 0 ? (
        <>
          <h2 style={{ fontSize: 18, margin: "8px 0 0" }}>Tills</h2>
          {regs.map((r) => {
            if (r.payment_methods === undefined)
              return (
                <p key={r.id} className="field-label">
                  {r.name}: update Friday in Friday Host to give a till its own methods.
                </p>
              );
            const own = r.payment_methods;
            return (
              <div key={r.id} style={{ display: "grid", gap: 8, padding: "8px 0", borderTop: "1px solid var(--border)" }}>
                <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <Checkbox
                    checked={own === null}
                    disabled={!canEdit}
                    onChange={() => saveTill(r, own === null ? methods : null)}
                  />
                  <span>
                    <strong>{r.name}</strong>
                    {r.location_name ? <span className="field-label"> · {r.location_name}</span> : null} takes what the
                    business takes
                  </span>
                </label>
                {own !== null
                  ? boxes(
                      own,
                      (m) => {
                        const next = toggle(own, m);
                        if (next.length) saveTill(r, next);
                      },
                      !canEdit,
                    )
                  : null}
              </div>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
