import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { useMyPermissions } from "../lib/permissions";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

interface Product {
  id: string;
  name: string;
  sku: string;
  barcode: string;
  on_hand_qty: number | string;
  reorder_point: number | string;
  track_inventory: boolean;
}
interface PurchaseOrder {
  id: string;
  number: string;
  status: string;
  supplier_status?: string;
}

const qty = (v: number | string) => Number(v) || 0;
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Warehouse work: count a shelf (the difference goes in as an adjustment,
 * booked at cost), take in a delivery, and see what's running low. With
 * the purchasing job too: mark ordered purchase orders received.
 * Inventory's rules decide which locations are mine. */
export function WarehouseWork() {
  const me = useMyPermissions();
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const buyer = Boolean(me?.rules["purchasing.write"]);

  const load = useCallback(() => {
    api
      .get<Product[]>("/api/inventory/products")
      .then((ps) => setProducts(ps.filter((p) => p.track_inventory)))
      .catch((err) => setError(errorText(err, "Could not load the stock")));
    if (buyer)
      api
        .get<PurchaseOrder[]>("/api/inventory/purchase_orders")
        .then((os) => setOrders(os.filter((o) => o.status === "ordered")))
        .catch(() => {});
  }, [buyer]);
  useEffect(load, [load]);

  async function receive(po: PurchaseOrder) {
    setError(null);
    try {
      await api.patch(`/api/inventory/purchase_orders/${po.id}/status`, { status: "received" });
      load();
    } catch (err) {
      setError(errorText(err, "Could not mark it received"));
    }
  }

  const low = (products ?? []).filter((p) => qty(p.on_hand_qty) <= Math.max(0, qty(p.reorder_point)));

  return (
    <>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <section aria-label="Count or take in stock">
        <h2 className="minions-group">Count or take in stock</h2>
        <StockCount products={products} onSaved={load} onError={setError} />
      </section>

      <section aria-label="Move to another store">
        <h2 className="minions-group">Move to another store</h2>
        <MoveStock products={products} onError={setError} />
      </section>

      {orders.length ? (
        <section aria-label="Deliveries expected">
          <h2 className="minions-group">Deliveries expected</h2>
          <ul className="minions-rows">
            {orders.map((o) => (
              <li key={o.id} className="minions-row">
                <div className="minions-row-main">
                  <span className="minions-row-title">{o.number}</span>
                  <span className="field-label">{o.supplier_status ? `Supplier: ${o.supplier_status}` : "Ordered"}</span>
                </div>
                <Button size="sm" variant="primary" onClick={() => receive(o)}>
                  It's here
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-label="Running low">
        <h2 className="minions-group">Running low</h2>
        {products && low.length === 0 ? <p className="field-label">Nothing is below its reorder point.</p> : null}
        {low.length ? (
          <ul className="minions-rows">
            {low.map((p) => (
              <li key={p.id} className="minions-row">
                <div className="minions-row-main">
                  <span className="minions-row-title">{p.name}</span>
                  <span className="field-label">
                    {qty(p.on_hand_qty)} left, reorder at {qty(p.reorder_point)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </>
  );
}

function StockCount({
  products,
  onSaved,
  onError,
}: {
  products: Product[] | null;
  onSaved: () => void;
  onError: (m: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Product | null>(null);
  const [mode, setMode] = useState<"count" | "in">("count");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const q = search.trim().toLowerCase();
  const matches = q
    ? (products ?? [])
        .filter((p) => p.name.toLowerCase().includes(q) || p.sku.toLowerCase() === q || p.barcode === search.trim())
        .slice(0, 8)
    : [];

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!picked) return;
    const n = Number.parseFloat(amount);
    if (!Number.isFinite(n) || n < 0 || (mode === "in" && n <= 0)) {
      onError(mode === "count" ? "Enter how many you counted" : "Enter how many came in");
      return;
    }
    const before = qty(picked.on_hand_qty);
    const delta = mode === "count" ? n - before : n;
    if (delta === 0) {
      setDone(`${picked.name}: ${before}, as the books say. Nothing to change.`);
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api.post(`/api/inventory/products/${picked.id}/adjust-stock`, {
        delta,
        reason: mode === "count" ? "manual_adjustment" : "received",
        reference: note.trim() || (mode === "count" ? "shelf count" : "delivery"),
      });
      setDone(`${picked.name}: ${before} → ${before + delta}.`);
      setPicked(null);
      setSearch("");
      setAmount("");
      setNote("");
      onSaved();
    } catch (err) {
      onError(errorText(err, "Could not save the count"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="minions-newclaim" onSubmit={save}>
      <fieldset className="minions-choice">
        <legend>What are you doing?</legend>
        <button type="button" aria-pressed={mode === "count"} onClick={() => setMode("count")}>
          Counting a shelf
        </button>
        <button type="button" aria-pressed={mode === "in"} onClick={() => setMode("in")}>
          Taking in a delivery
        </button>
      </fieldset>
      {picked ? (
        <p className="minions-row-title">
          {picked.name}{" "}
          <span className="field-label">
            ({qty(picked.on_hand_qty)} on the books){" "}
            <button type="button" className="bell-link" onClick={() => setPicked(null)}>
              Change
            </button>
          </span>
        </p>
      ) : (
        <FieldWrap label="Product (name, SKU or barcode)" required>
          <Input value={search} placeholder="e.g. Sugar 2kg" onChange={(e) => setSearch(e.target.value)} />
        </FieldWrap>
      )}
      {!picked && matches.length ? (
        <ul className="minions-rows">
          {matches.map((p) => (
            <li key={p.id}>
              <button type="button" className="bell-item" onClick={() => setPicked(p)}>
                <span className="bell-title">{p.name}</span>
                <span className="bell-time">{qty(p.on_hand_qty)} on the books</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {picked ? (
        <>
          <FieldWrap label={mode === "count" ? "How many are there?" : "How many came in?"} required>
            <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Note (optional)">
            <Input value={note} maxLength={120} placeholder={mode === "count" ? "e.g. Shelf 4" : "e.g. Delivery note 2231"} onChange={(e) => setNote(e.target.value)} />
          </FieldWrap>
        </>
      ) : null}
      {done ? (
        <p className="field-label" role="status">
          {done}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy || !picked}>
        {busy ? "Saving…" : "Save"}
      </Button>
    </form>
  );
}

interface Place {
  id: string;
  name: string;
}

/** Moving stock from one store to another: one step on the server (out
 * of one, into the other together), never more than is there. */
function MoveStock({ products, onError }: { products: Product[] | null; onError: (m: string | null) => void }) {
  const [places, setPlaces] = useState<Place[]>([]);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Product | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Place[]>("/api/inventory/warehouses")
      .then(setPlaces)
      .catch(() => {});
  }, []);

  const q = search.trim().toLowerCase();
  const matches = q
    ? (products ?? []).filter((p) => p.name.toLowerCase().includes(q) || p.barcode === search.trim()).slice(0, 6)
    : [];

  async function move(e: FormEvent) {
    e.preventDefault();
    const n = Number.parseFloat(amount);
    if (!picked || !from || !to || !(n > 0)) {
      onError("Choose the product, both places, and how many");
      return;
    }
    if (from === to) {
      onError("Choose two different places");
      return;
    }
    setBusy(true);
    onError(null);
    setDone(null);
    try {
      await api.post(`/api/inventory/products/${picked.id}/transfer`, { from_warehouse_id: from, to_warehouse_id: to, qty: n });
      const name = (id: string) => places.find((p) => p.id === id)?.name ?? "";
      setDone(`Moved ${n} ${picked.name} from ${name(from)} to ${name(to)}.`);
      setPicked(null);
      setSearch("");
      setAmount("");
    } catch (err) {
      onError(errorText(err, "Could not move the stock"));
    } finally {
      setBusy(false);
    }
  }

  if (places.length < 2) {
    return <p className="field-label">Moving stock needs two stores or warehouses. Your manager adds them in Inventory.</p>;
  }
  return (
    <form className="minions-newclaim" onSubmit={move}>
      {picked ? (
        <p className="minions-row-title">
          {picked.name}{" "}
          <button type="button" className="bell-link" onClick={() => setPicked(null)}>
            Change
          </button>
        </p>
      ) : (
        <FieldWrap label="Product" required>
          <Input value={search} placeholder="e.g. Sugar 2kg" onChange={(e) => setSearch(e.target.value)} />
        </FieldWrap>
      )}
      {!picked && matches.length ? (
        <ul className="minions-rows">
          {matches.map((p) => (
            <li key={p.id}>
              <button type="button" className="bell-item" onClick={() => setPicked(p)}>
                <span className="bell-title">{p.name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="minions-two">
        <FieldWrap label="From" required>
          <Select value={from} onChange={(e) => setFrom(e.target.value)}>
            <option value="" disabled>
              Choose…
            </option>
            {places.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </FieldWrap>
        <FieldWrap label="To" required>
          <Select value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="" disabled>
              Choose…
            </option>
            {places.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </FieldWrap>
      </div>
      <FieldWrap label="How many" required>
        <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
      </FieldWrap>
      {done ? (
        <p className="field-label" role="status">
          {done}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Moving…" : "Move stock"}
      </Button>
    </form>
  );
}
