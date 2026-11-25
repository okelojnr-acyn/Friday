import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";

interface Passkey {
  id: string;
  device_label: string;
  created_at: string;
}

interface Device {
  id: string;
  label: string;
  ip: string;
  signed_in_at: string;
  last_seen_at: string;
  current: boolean;
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const row = { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "8px 0" } as const;

/** Your sign-in: passkeys (add, remove) and the devices you're signed in
 * on (sign one out, or all the others). */
export function AccountPage() {
  const { session, addPasskey, logout } = useAuth();
  const [passkeys, setPasskeys] = useState<Passkey[] | null>(null);
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, d] = await Promise.all([api.get<Passkey[]>("/auth/passkeys"), api.get<Device[]>("/auth/sessions")]);
      setPasskeys(p);
      setDevices(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your sign-in settings");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const others = (devices ?? []).filter((d) => !d.current);

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Your account</h1>
        <span className="field-label">{session?.email}</span>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}

      <div className="card card-padded" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>Passkeys</h2>
        <p className="field-label" style={{ marginTop: 0 }}>
          Sign in with your fingerprint or face. Add one on each phone or computer you use; without one, you sign in
          with an email code.
        </p>
        {passkeys === null ? (
          <div className="spinner">Loading…</div>
        ) : passkeys.length === 0 ? (
          <p>No passkeys yet.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {passkeys.map((p) => (
              <li key={p.id} style={row}>
                <span>
                  {p.device_label || "Passkey"}
                  <span className="field-label" style={{ display: "block" }}>
                    Added {when(p.created_at)}
                  </span>
                </span>
                <Button disabled={busy} onClick={() => run(() => api.del(`/auth/passkeys/${encodeURIComponent(p.id)}`))}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="form-grid" style={{ marginTop: 12 }}>
          <FieldWrap label="Name this device (optional)">
            <Input value={label} maxLength={60} placeholder="e.g. Work laptop" onChange={(e) => setLabel(e.target.value)} />
          </FieldWrap>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await addPasskey({ label });
                setLabel("");
              })
            }
          >
            Add a passkey on this device
          </Button>
        </div>
      </div>

      <div className="card card-padded" style={{ marginTop: 16 }}>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>Devices</h2>
        <p className="field-label" style={{ marginTop: 0 }}>
          Where you're signed in. Sign out any you don't recognise; it stops working within a minute.
        </p>
        {devices === null ? (
          <div className="spinner">Loading…</div>
        ) : devices.length === 0 ? (
          <p>Devices show here from your next sign-in.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {devices.map((d) => (
              <li key={d.id} style={row}>
                <span>
                  {d.label}
                  {d.current ? <span className="field-label"> · this device</span> : null}
                  <span className="field-label" style={{ display: "block" }}>
                    Signed in {when(d.signed_in_at)} · last active {when(d.last_seen_at)}
                    {d.ip ? ` · ${d.ip}` : ""}
                  </span>
                </span>
                <Button
                  disabled={busy}
                  onClick={() => (d.current ? logout() : run(() => api.del(`/auth/sessions/${encodeURIComponent(d.id)}`)))}
                >
                  Sign out
                </Button>
              </li>
            ))}
          </ul>
        )}
        {others.length > 1 ? (
          <Button disabled={busy} onClick={() => run(() => api.post("/auth/sessions/sign-out-others", {}))}>
            Sign out all other devices
          </Button>
        ) : null}
      </div>
    </div>
  );
}
