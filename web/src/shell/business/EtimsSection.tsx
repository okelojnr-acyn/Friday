import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { Button } from "../../ui/Button";
import { Checkbox, FieldWrap, Input, Select } from "../../ui/Field";
import { SaveRow } from "./SaveRow";

interface EtimsSettings {
  enabled: boolean;
  environment: "sandbox" | "production";
  mode: "oscu" | "vscu";
  branch_id: string;
  device_serial: string;
  vscu_url: string;
  cmc_key_set: boolean;
  updated_at: string | null;
  tax_pin: string;
}

/** Business settings > eTIMS: how this business reaches KRA's
 * electronic tax invoice system (kernel /orgs/etims). The CMC key is
 * write-only: the page says whether one is stored, never shows it. */
export function EtimsSection({ canEdit }: { canEdit: boolean }) {
  const [v, setV] = useState<EtimsSettings | null>(null);
  const [cmcKey, setCmcKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!canEdit) return;
    api
      .get<EtimsSettings>("/orgs/etims")
      .then(setV)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the eTIMS settings."));
  }, [canEdit]);

  if (!canEdit) {
    return (
      <div className="card card-padded">
        <p className="field-label">Only owners and admins see eTIMS settings.</p>
      </div>
    );
  }
  if (!v) {
    return <div className="card card-padded">{error ? <div className="error-banner">{error}</div> : "Loading…"}</div>;
  }

  const set = <K extends keyof EtimsSettings>(k: K, val: EtimsSettings[K]) => setV((x) => (x ? { ...x, [k]: val } : x));

  async function save(extra?: { clear_cmc_key?: boolean }) {
    if (!v) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const body: Record<string, unknown> = {
        enabled: v.enabled,
        environment: v.environment,
        mode: v.mode,
        branch_id: v.branch_id,
        device_serial: v.device_serial,
        vscu_url: v.vscu_url,
        ...extra,
      };
      if (cmcKey.trim()) body.cmc_key = cmcKey.trim();
      setV(await api.put<EtimsSettings>("/orgs/etims", body));
      setCmcKey("");
      setNotice("Saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="field-label">{notice}</div> : null}
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        KRA approves the device and gives you the branch ID and device serial. Initialising the device returns the CMC
        key. Test on the sandbox before switching to production.
      </p>
      <FieldWrap label="KRA PIN">
        <div style={{ fontFamily: "var(--font-mono, monospace)" }}>
          {v.tax_pin || (
            <span className="field-label">
              Not set. Add it under <Link to="/settings/business?tab=tax">Tax</Link>.
            </span>
          )}
        </div>
      </FieldWrap>
      <FieldWrap label="Integration">
        <Select value={v.mode} onChange={(e) => set("mode", e.target.value as EtimsSettings["mode"])}>
          <option value="oscu">OSCU: online, Friday talks to KRA</option>
          <option value="vscu">VSCU: a sales control unit on your network</option>
        </Select>
      </FieldWrap>
      <FieldWrap label="Environment">
        <Select value={v.environment} onChange={(e) => set("environment", e.target.value as EtimsSettings["environment"])}>
          <option value="sandbox">Sandbox (testing)</option>
          <option value="production">Production</option>
        </Select>
      </FieldWrap>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <FieldWrap label="Branch ID">
          <Input
            name="etims-branch"
            autoComplete="off"
            value={v.branch_id}
            maxLength={2}
            onChange={(e) => set("branch_id", e.target.value.replace(/\D/g, ""))}
            style={{ width: 80 }}
          />
        </FieldWrap>
        <FieldWrap label="Device serial number">
          <Input
            name="etims-device-serial"
            autoComplete="off"
            value={v.device_serial}
            onChange={(e) => set("device_serial", e.target.value)}
            style={{ width: 240 }}
          />
        </FieldWrap>
      </div>
      {v.mode === "vscu" ? (
        <FieldWrap label="VSCU address">
          <Input
            name="etims-vscu-url"
            autoComplete="off"
            placeholder="http://192.168.1.20:8088"
            value={v.vscu_url}
            onChange={(e) => set("vscu_url", e.target.value)}
          />
        </FieldWrap>
      ) : null}
      <FieldWrap label="CMC key">
        <Input
          type="password"
          name="etims-cmc-key"
          autoComplete="new-password"
          placeholder={v.cmc_key_set ? "Stored. Type a new one to replace it." : "From device initialisation"}
          value={cmcKey}
          onChange={(e) => setCmcKey(e.target.value)}
        />
      </FieldWrap>
      {v.cmc_key_set ? (
        <div>
          <Button size="sm" onClick={() => save({ clear_cmc_key: true })} disabled={saving}>
            Remove the stored key
          </Button>
        </div>
      ) : null}
      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Checkbox checked={v.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        Turn on eTIMS for this business
      </label>
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        Sending sales to KRA is the next step being built. Until then these settings are stored and checked, and no sale
        is reported.
      </p>
      <SaveRow canEdit={canEdit} saving={saving} onSave={() => save()} />
    </div>
  );
}
