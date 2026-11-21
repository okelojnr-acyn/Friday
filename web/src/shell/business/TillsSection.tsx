import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { listLocations, type Location } from "../../lib/people";
import { createRegister, listRegisters, updateRegister, type PosRegister } from "../../lib/posApi";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { FieldWrap, Input, Select } from "../../ui/Field";

/** Business settings > Tills: the only tills a POS device can be. The
 * POS picks from this list and never makes one up. */
export function TillsSection({ canEdit }: { canEdit: boolean }) {
  const [regs, setRegs] = useState<PosRegister[] | null>(null);
  // The business's locations (People > Locations); a till stands in one.
  const [locations, setLocations] = useState<Location[]>([]);
  useEffect(() => {
    listLocations().then(setLocations).catch(() => {});
  }, []);
  const locName = (id: string) => locations.find((l) => l.id === id)?.name ?? "";
  const [name, setName] = useState("");
  const [store, setStore] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editStore, setEditStore] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    listRegisters()
      .then(setRegs)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the tills."));
  }
  useEffect(load, []);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (await run(() => createRegister(name.trim(), locName(store), store || null))) {
      setName("");
      setStore("");
    }
  }

  async function saveEdit(id: string) {
    if (await run(() => updateRegister(id, { name: editName.trim(), location_name: locName(editStore), location_id: editStore || null })))
      setEditing(null);
  }

  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      <p className="field-label" style={{ maxWidth: "60ch", margin: 0 }}>
        Each till has its own drawer, shift and cash count. A POS device asks which of these tills it is the first time
        it opens.
      </p>
      {regs === null ? (
        <div className="field-label">Loading…</div>
      ) : regs.length === 0 ? (
        <div className="field-label">No tills yet. Add the first one below.</div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {regs.map((r) =>
            editing === r.id ? (
              <div key={r.id} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Input aria-label="Till name" autoComplete="off" value={editName} maxLength={60} onChange={(e) => setEditName(e.target.value)} style={{ flex: "1 1 140px", minWidth: 0 }} />
                <Select aria-label="Location" value={editStore} onChange={(e) => setEditStore(e.target.value)} style={{ flex: "1 1 140px", minWidth: 0 }}>
                  <option value="">No location</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </Select>
                <Button size="sm" variant="primary" disabled={busy || !editName.trim()} onClick={() => saveEdit(r.id)}>
                  Save
                </Button>
                <Button size="sm" onClick={() => setEditing(null)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <div
                key={r.id}
                style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--border)" }}
              >
                <div style={{ flex: "1 1 200px", minWidth: 0 }}>
                  <strong>{r.name}</strong>
                  {r.location_name ? <span className="field-label"> · {r.location_name}</span> : null}
                </div>
                {r.open_shift ? <Badge>open</Badge> : null}
                {!r.active ? <Badge>switched off</Badge> : null}
                {canEdit ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => {
                        setEditing(r.id);
                        setEditName(r.name);
                        setEditStore(r.location_id ?? "");
                      }}
                    >
                      Rename
                    </Button>
                    <Button size="sm" disabled={busy} onClick={() => run(() => updateRegister(r.id, { active: !r.active }))}>
                      {r.active ? "Switch off" : "Switch on"}
                    </Button>
                  </>
                ) : null}
              </div>
            ),
          )}
        </div>
      )}
      {canEdit ? (
        <>
          <h2 style={{ fontSize: 18, margin: "8px 0 0" }}>Add a till</h2>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <FieldWrap label="Name" required>
              <Input name="till-name" autoComplete="off" placeholder="Till 2" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="Location">
              <Select name="till-location" value={store} onChange={(e) => setStore(e.target.value)}>
                <option value="">No location</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            </FieldWrap>
            <Button variant="primary" disabled={busy || !name.trim()} onClick={add}>
              Add till
            </Button>
          </div>
        </>
      ) : (
        <p className="field-label">Only owners and admins add tills.</p>
      )}
    </div>
  );
}
