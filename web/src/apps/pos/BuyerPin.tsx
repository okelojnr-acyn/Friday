import { useState } from "react";
import { api } from "../../lib/api";

export interface Buyer {
  pin: string;
  name: string;
}

interface PinCheck {
  pin: string;
  format_ok: boolean;
  verified: boolean | null;
  name: string;
  active: boolean | null;
  checker_url: string;
}

const PIN = /^[AP][0-9]{9}[A-Z]$/;

/** A business buying gives its KRA PIN; it goes on the receipt and on the
 * eTIMS invoice, so the buyer can claim the VAT and the expense. Checked
 * for format here; with automatic eTIMS on, KRA says whose PIN it is. */
export function BuyerPin({ value, onChange }: { value: Buyer | null; onChange: (b: Buyer | null) => void }) {
  const [open, setOpen] = useState(false);
  const [pin, setPin] = useState(value?.pin ?? "");
  const [name, setName] = useState(value?.name ?? "");
  const [check, setCheck] = useState<PinCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const clean = pin.trim().toUpperCase().replace(/\s/g, "");
  const formatOk = PIN.test(clean);

  async function verify() {
    if (!formatOk) return;
    setChecking(true);
    try {
      const c = await api.get<PinCheck>(`/api/invoicing/etims/pin/${encodeURIComponent(clean)}`);
      setCheck(c);
      if (c.name && !name.trim()) setName(c.name);
    } catch {
      setCheck(null); // offline: the format check still holds; the PIN is checked when filed
    } finally {
      setChecking(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="till-chip glass" style={{ cursor: "pointer", justifySelf: "start" }} onClick={() => setOpen(true)}>
        {value ? `Buyer PIN ${value.pin}${value.name ? ` · ${value.name}` : ""}` : "Business customer? Add KRA PIN"}
      </button>
    );
  }

  return (
    <div className="glass" style={{ borderRadius: 20, padding: 16, display: "grid", gap: 10 }}>
      <div className="till-text" style={{ fontWeight: 600 }}>Customer's KRA PIN</div>
      <input
        className="till-input"
        placeholder="P051234567X"
        autoComplete="off"
        name="buyer-kra-pin"
        value={pin}
        maxLength={14}
        onChange={(e) => {
          setPin(e.target.value.toUpperCase());
          setCheck(null);
        }}
        onBlur={verify}
        autoFocus
      />
      {pin && !formatOk ? <div className="till-error" style={{ margin: 0 }}>A KRA PIN is A or P, nine digits, then a letter.</div> : null}
      {check?.verified === true ? (
        <div className="till-text">
          KRA: {check.name}
          {check.active === false ? " (inactive PIN)" : ""}
        </div>
      ) : check?.verified === false ? (
        <div className="till-error" style={{ margin: 0 }}>KRA has no taxpayer with this PIN.</div>
      ) : formatOk && check ? (
        <div className="till-text" style={{ fontSize: 14 }}>
          Format is right.{" "}
          <a href={check.checker_url} target="_blank" rel="noopener noreferrer">
            Check it on KRA's PIN checker
          </a>
        </div>
      ) : null}
      <input
        className="till-input"
        placeholder="Business name (as on the PIN)"
        autoComplete="off"
        name="buyer-business-name"
        value={name}
        maxLength={120}
        onChange={(e) => setName(e.target.value)}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className="till-btn primary"
          disabled={!formatOk || checking || check?.verified === false}
          onClick={() => {
            onChange({ pin: clean, name: name.trim() });
            setOpen(false);
          }}
        >
          {checking ? "Checking…" : "Use this PIN"}
        </button>
        <button
          type="button"
          className="till-btn"
          onClick={() => {
            onChange(null);
            setPin("");
            setName("");
            setCheck(null);
            setOpen(false);
          }}
        >
          {value ? "Remove" : "Cancel"}
        </button>
      </div>
    </div>
  );
}
