import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { api, ApiError } from "../lib/api";
import { localDay } from "../lib/localTime";
import { useMyPermissions } from "../lib/permissions";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Work (HR plan 8.2): one section per job the person holds. Drivers now;
 * warehouse and sales next. */
export function WorkPage() {
  const me = useMyPermissions();
  const driver = Boolean(me?.rules["deliveries.write"]);
  return (
    <div className="page minions-page">
      <h1 className="page-title">Work</h1>
      {driver ? <DriverWork /> : null}
      {me && !driver ? (
        <div className="minions-empty">
          <p className="minions-empty-title">Nothing here for your job yet</p>
          <p className="field-label">Your manager sets your jobs in People. Tasks given to you are on Today.</p>
        </div>
      ) : null}
    </div>
  );
}

interface Parcel {
  id: string;
  tracking_code: string;
  description: string;
  recipient_name: string;
  recipient_phone: string;
  destination: string;
  status: "received" | "out_for_delivery" | "delivered" | "returned";
  holder_email: string;
  updated_at: string;
}
interface Vehicle {
  id: string;
  name?: string;
  plate_number?: string;
  make?: string;
  model?: string;
  assigned_driver_name?: string;
}
interface Driver {
  email: string;
  license_expires_on: string | null;
}

/** A driver's day: the parcels I'm carrying (call, directions, delivered,
 * returned), picking one up by its code, fuel for my vehicle, and a
 * warning before my licence runs out. Fleets decides what's mine. */
function DriverWork() {
  const { session } = useAuth();
  const [parcels, setParcels] = useState<Parcel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [licence, setLicence] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<Parcel[]>("/api/fleets/parcels")
      .then(setParcels)
      .catch((err) => setError(errorText(err, "Could not load your deliveries")));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api
      .get<Driver[]>("/api/fleets/drivers")
      .then((ds) => {
        const mine = ds.find((d) => d.email && d.email.toLowerCase() === session?.email.toLowerCase());
        setLicence(mine?.license_expires_on ?? null);
      })
      .catch(() => {});
  }, [session?.email]);

  async function scan(code: string, action: "out" | "delivered" | "returned", note = "") {
    setError(null);
    try {
      await api.post("/api/fleets/parcels/scan", { code, action, note });
      load();
    } catch (err) {
      setError(errorText(err, "Could not save that"));
      throw err;
    }
  }

  const carrying = (parcels ?? []).filter((p) => p.status === "out_for_delivery" && p.holder_email.toLowerCase() === session?.email.toLowerCase());
  const daysLeft = licence ? Math.ceil((new Date(`${licence}T12:00:00`).getTime() - Date.now()) / 86_400_000) : null;

  return (
    <>
      {daysLeft !== null && daysLeft <= 30 ? (
        <div className={daysLeft < 0 ? "error-banner" : "minions-notice"} role="status">
          {daysLeft < 0
            ? "Your driving licence has expired. Renew it before driving, and tell your manager."
            : `Your driving licence runs out in ${daysLeft} ${daysLeft === 1 ? "day" : "days"}.`}
        </div>
      ) : null}
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      <section aria-label="Deliveries">
        <h2 className="minions-group">Deliveries I'm carrying</h2>
        {parcels === null && !error ? <div className="spinner">Loading…</div> : null}
        {parcels && carrying.length === 0 ? (
          <div className="minions-empty">
            <p className="minions-empty-title">Nothing to deliver</p>
            <p className="field-label">Pick a parcel up below, or scan it out on Telegram, and it shows here.</p>
          </div>
        ) : null}
        <ul className="minions-cardlist">
          {carrying.map((p) => (
            <ParcelCard key={p.id} parcel={p} onScan={scan} />
          ))}
        </ul>
      </section>

      <section aria-label="Pick up a parcel">
        <h2 className="minions-group">Pick up a parcel</h2>
        <PickUp onScan={scan} />
      </section>

      <section aria-label="Fuel">
        <h2 className="minions-group">Fuel</h2>
        <FuelForm onError={setError} />
      </section>
    </>
  );
}

function ParcelCard({
  parcel: p,
  onScan,
}: {
  parcel: Parcel;
  onScan: (code: string, action: "delivered" | "returned", note?: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (action: "delivered" | "returned") => {
    setBusy(true);
    try {
      await onScan(p.tracking_code, action, note);
    } catch {
      // shown above
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="minions-parcel">
      <p className="minions-row-title">{p.recipient_name || p.description || p.tracking_code}</p>
      <p className="field-label">
        {p.tracking_code}
        {p.description && p.recipient_name ? `, ${p.description}` : ""}
      </p>
      {p.destination ? <p>{p.destination}</p> : null}
      <div className="minions-actions">
        {p.recipient_phone ? (
          <a className="btn btn-secondary btn-sm" href={`tel:${p.recipient_phone.replace(/[^\d+]/g, "")}`}>
            Call {p.recipient_phone}
          </a>
        ) : null}
        {p.destination ? (
          <a
            className="btn btn-secondary btn-sm"
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.destination)}`}
            target="_blank"
            rel="noreferrer"
          >
            Directions
          </a>
        ) : null}
      </div>
      <FieldWrap label="Note (optional)">
        <Input value={note} maxLength={300} placeholder="e.g. Left with the guard" onChange={(e) => setNote(e.target.value)} />
      </FieldWrap>
      <div className="minions-actions">
        <Button variant="primary" disabled={busy} onClick={() => act("delivered")}>
          Delivered
        </Button>
        <Button disabled={busy} onClick={() => act("returned")}>
          Couldn't deliver
        </Button>
      </div>
    </li>
  );
}

function PickUp({ onScan }: { onScan: (code: string, action: "out") => Promise<void> }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  async function pick(e: FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setDone(null);
    try {
      await onScan(code.trim(), "out");
      setDone(`${code.trim()} is with you now.`);
      setCode("");
    } catch {
      // shown above
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="minions-newclaim" onSubmit={pick}>
      <FieldWrap label="Tracking code" required>
        <Input value={code} maxLength={128} autoCapitalize="characters" placeholder="e.g. WB-1042" onChange={(e) => setCode(e.target.value)} />
      </FieldWrap>
      {done ? (
        <p className="field-label" role="status">
          {done}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Saving…" : "I'm taking it out"}
      </Button>
    </form>
  );
}

function FuelForm({ onError }: { onError: (m: string | null) => void }) {
  const { session } = useAuth();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehicle, setVehicle] = useState("");
  const [litres, setLitres] = useState("");
  const [cost, setCost] = useState("");
  const [odometer, setOdometer] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Vehicle[]>("/api/fleets/vehicles")
      .then((vs) => {
        setVehicles(vs);
        // The one assigned to me, when the fleet says so.
        const name = session?.email.split("@")[0].toLowerCase() ?? "";
        const mine = vs.find((v) => v.assigned_driver_name && name && v.assigned_driver_name.toLowerCase().includes(name));
        if (mine) setVehicle(mine.id);
      })
      .catch(() => {});
  }, [session?.email]);

  async function log(e: FormEvent) {
    e.preventDefault();
    const quantity = Math.round(Number.parseFloat(litres || "0"));
    if (!vehicle || quantity <= 0) {
      onError("Choose the vehicle and enter how much fuel");
      return;
    }
    setBusy(true);
    onError(null);
    setDone(null);
    try {
      await api.post("/api/fleets/fuel_logs", {
        vehicle_id: vehicle,
        fill_date: localDay(),
        quantity,
        cost_cents: Math.round((Number.parseFloat(cost || "0") || 0) * 100),
        odometer: Math.round(Number.parseFloat(odometer || "0") || 0),
      });
      setDone("Fuel saved.");
      setLitres("");
      setCost("");
      setOdometer("");
    } catch (err) {
      onError(errorText(err, "Could not save the fuel"));
    } finally {
      setBusy(false);
    }
  }

  if (vehicles.length === 0) return <p className="field-label">No vehicles yet. Your manager adds them in Fleets.</p>;
  const label = (v: Vehicle) => [v.name, v.plate_number, v.make, v.model].filter(Boolean).join(" ") || "Vehicle";
  return (
    <form className="minions-newclaim" onSubmit={log}>
      <FieldWrap label="Vehicle" required>
        <Select value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
          <option value="" disabled>
            Choose…
          </option>
          {vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              {label(v)}
            </option>
          ))}
        </Select>
      </FieldWrap>
      <div className="minions-two">
        <FieldWrap label="Litres" required>
          <Input value={litres} inputMode="decimal" onChange={(e) => setLitres(e.target.value)} />
        </FieldWrap>
        <FieldWrap label="Cost">
          <Input value={cost} inputMode="decimal" onChange={(e) => setCost(e.target.value)} />
        </FieldWrap>
      </div>
      <FieldWrap label="Odometer (km)">
        <Input value={odometer} inputMode="numeric" onChange={(e) => setOdometer(e.target.value)} />
      </FieldWrap>
      {done ? (
        <p className="field-label" role="status">
          {done}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Saving…" : "Save fuel"}
      </Button>
    </form>
  );
}
