import { useEffect, useMemo, useRef, useState } from "react";
import init, { PosCart, PosOfflineQueue } from "./engine/friday_pos_engine";
import { api, ApiError } from "../../lib/api";
import { fetchProductCatalog, type Product } from "../../lib/inventory";
import { useBarcodeScanner } from "../../lib/useBarcodeScanner";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Field";
import { Badge } from "../../ui/Badge";
import { Icon } from "../../ui/Icon";
import { ReturnsPanel } from "./ReturnsPanel";

interface CartLine {
  description: string;
  quantity: number;
  unit_price_cents: number;
  product_id: string | null;
  discount_bp: number;
  unit_cost_cents: number | null;
}

function lineTotalCents(line: CartLine): number {
  return Math.round((line.quantity * line.unit_price_cents * (10_000 - line.discount_bp)) / 10_000);
}

interface Sale {
  client_sale_id: string;
  lines: CartLine[];
  currency: string;
  method: string;
  amount_cents: number;
  created_at_ms: number;
}

const QUEUE_STORAGE_KEY = "friday.pos.offline_queue";
const TAX_RATE_BP = 800; // 8% -- a flat dev default; a real deployment would read this from org settings
const NUMPAD_KEYS = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "+/-", "0", "."];

/** The one genuinely custom screen in the product (see ARCHITECTURE.md):
 * a cart with live tax math and offline-first checkout isn't a CRUD form,
 * so it doesn't go through the generic ResourceSpec renderer. All of the
 * actual pricing/tax/queue logic lives in pos-engine (Rust, compiled to
 * WASM) -- this component is the register UI around it: scan a barcode,
 * search the catalog, or type a freeform line; select a line and type a
 * new quantity or price on the numpad (same interaction model as a real
 * register). */
export function PosPage() {
  const [ready, setReady] = useState(false);
  const cartRef = useRef<PosCart | null>(null);
  const queueRef = useRef<PosOfflineQueue | null>(null);

  const [lines, setLines] = useState<CartLine[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [totals, setTotals] = useState({ subtotal: 0, tax: 0, total: 0 });
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSale, setLastSale] = useState<Sale | null>(null);

  const [description, setDescription] = useState("");
  const [unitPrice, setUnitPrice] = useState("");

  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<"qty" | "price" | "discount">("qty");
  const [buffer, setBuffer] = useState("");
  const [showReturns, setShowReturns] = useState(false);

  useEffect(() => {
    init().then(() => {
      // wasm-bindgen maps Rust's i64 to JS BigInt (a JS number can't
      // represent all 64-bit integers precisely) -- every cents amount
      // crossing the wasm boundary needs this conversion.
      cartRef.current = new PosCart(BigInt(TAX_RATE_BP));
      const stored = localStorage.getItem(QUEUE_STORAGE_KEY);
      queueRef.current = stored ? PosOfflineQueue.restore_json(stored) : new PosOfflineQueue();
      setPendingCount(queueRef.current.len());
      setReady(true);
    });
    fetchProductCatalog().then(setProducts);
  }, []);

  function refreshCart() {
    const cart = cartRef.current;
    if (!cart) return;
    setLines(JSON.parse(cart.lines_json()));
    setTotals({
      subtotal: Number(cart.subtotal_cents()),
      tax: Number(cart.tax_cents()),
      total: Number(cart.total_cents()),
    });
  }

  /** pos-engine has no "update qty/price" method -- it's append/remove/
   * clear only (see pos-engine/src/wasm.rs). Editing a line's qty/price
   * here rebuilds the cart from the edited line list so the Rust engine
   * stays the single source of truth for totals/tax, instead of this
   * component re-deriving money math in JS. add_line always resets a
   * line's discount to 0, so each line's existing discount_bp is
   * reapplied via set_line_discount_bp afterward -- otherwise editing
   * one line's quantity would silently wipe every other line's discount. */
  function rebuildCart(newLines: CartLine[]) {
    const cart = cartRef.current;
    if (!cart) return;
    cart.clear();
    newLines.forEach((l, i) => {
      cart.add_line(
        l.description,
        l.quantity,
        BigInt(l.unit_price_cents),
        l.product_id ?? undefined,
        l.unit_cost_cents != null ? BigInt(l.unit_cost_cents) : undefined,
      );
      if (l.discount_bp) cart.set_line_discount_bp(i, BigInt(l.discount_bp));
    });
    refreshCart();
  }

  function persistQueue() {
    const queue = queueRef.current;
    if (!queue) return;
    localStorage.setItem(QUEUE_STORAGE_KEY, queue.to_json());
    setPendingCount(queue.len());
  }

  function addLine() {
    const cart = cartRef.current;
    const price = Math.round(Number.parseFloat(unitPrice || "0") * 100);
    if (!cart || !description.trim() || !Number.isFinite(price)) return;
    cart.add_line(description.trim(), 1, BigInt(price), undefined, undefined);
    setDescription("");
    setUnitPrice("");
    refreshCart();
    setSelected(lines.length); // select the line just added
    setMode("qty");
    setBuffer("");
  }

  function addFromCatalog(product: Product) {
    const cart = cartRef.current;
    if (!cart) return;
    cart.add_line(
      product.name,
      1,
      BigInt(product.price_cents),
      product.id,
      product.cost_cents ? BigInt(product.cost_cents) : undefined,
    );
    setSearch("");
    refreshCart();
    setSelected(lines.length);
    setMode("qty");
    setBuffer("");
  }

  function selectLine(i: number) {
    setSelected(i);
    setBuffer("");
  }

  function removeSelected() {
    if (selected === null) return;
    cartRef.current?.remove_line(selected);
    setSelected(null);
    setBuffer("");
    refreshCart();
  }

  function applyBuffer(next: string) {
    setBuffer(next);
    if (selected === null) return;
    const parsed = next === "" || next === "." ? 0 : Number.parseFloat(next);
    const value = Number.isFinite(parsed) ? parsed : 0;

    if (mode === "discount") {
      // The buffer is a percent-off, set directly on the line via the
      // engine (pos-engine/src/cart.rs's set_line_discount_bp) -- the
      // line's own unit_price_cents is never touched, so this can never
      // compound against an already-discounted price the way the old
      // mutate-unit_price_cents approach could.
      const pct = Math.min(Math.max(value, 0), 100);
      const bp = next === "" ? 0 : Math.round(pct * 100);
      cartRef.current?.set_line_discount_bp(selected, BigInt(bp));
      refreshCart();
      return;
    }

    const newLines = lines.map((l, i) => {
      if (i !== selected) return l;
      if (mode === "qty") return { ...l, quantity: next === "" ? l.quantity : value };
      return { ...l, unit_price_cents: next === "" ? l.unit_price_cents : Math.round(value * 100) };
    });
    rebuildCart(newLines);
  }

  function pressKey(key: string) {
    if (selected === null) return;
    if (key === "+/-") return; // quantities/prices are never negative in this register
    if (key === "." && buffer.includes(".")) return;
    applyBuffer(buffer + key);
  }

  function backspace() {
    if (selected === null) return;
    applyBuffer(buffer.slice(0, -1));
  }

  // Barcode scanner support: matches a scan against the cached catalog,
  // regardless of which element has focus. See useBarcodeScanner's own
  // doc comment for the scan-vs-typing detection this is built on.
  useBarcodeScanner((code) => {
    const match = products.find((p) => p.barcode && p.barcode === code);
    if (match) {
      addFromCatalog(match);
      setScanNotice(`Scanned: ${match.name}`);
    } else {
      setScanNotice(`No product with barcode ${code}`);
    }
    setTimeout(() => setScanNotice(null), 2500);
  });

  async function syncPending() {
    const queue = queueRef.current;
    if (!queue || queue.len() === 0 || syncing) return;
    setSyncing(true);
    const pending: Sale[] = JSON.parse(queue.pending_json());
    for (const sale of pending) {
      try {
        await api.post("/api/invoicing/pos/sales", sale);
        queue.mark_synced(sale.client_sale_id);
        persistQueue();
      } catch (err) {
        // offline, or invoicing is down -- leave it queued and try the rest
        if (!(err instanceof ApiError)) break;
      }
    }
    setSyncing(false);
  }

  useEffect(() => {
    if (!ready) return;
    syncPending();
    const onOnline = () => syncPending();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function checkout(method: "cash" | "card") {
    const cart = cartRef.current;
    const queue = queueRef.current;
    if (!cart || !queue || lines.length === 0) return;

    setError(null);
    const saleJson = cart.checkout_json("USD", method, Date.now());
    const sale: Sale = JSON.parse(saleJson);
    queue.enqueue_json(saleJson);
    persistQueue();
    cart.clear();
    setSelected(null);
    setBuffer("");
    refreshCart();
    setLastSale(sale);

    try {
      await api.post("/api/invoicing/pos/sales", sale);
      queue.mark_synced(sale.client_sale_id);
      persistQueue();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Sale saved locally; sync failed: ${err.message}`
          : "Sale saved locally; will sync once back online.",
      );
    }
  }

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return products
      .filter((p) => p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q))
      .slice(0, 6);
  }, [search, products]);

  if (!ready) return <div className="page spinner">Starting register...</div>;

  return (
    <div className="pos-screen">
      <div className="pos-cart-pane">
        <div className="pos-cart-header">
          <span className="pos-cart-title">Register</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {pendingCount > 0 ? (
              <Badge tone="accent">{`${pendingCount} pending sync`}</Badge>
            ) : (
              <Badge tone="success">Synced</Badge>
            )}
            <Button size="sm" variant="secondary" onClick={() => setShowReturns(true)}>
              <Icon name="history" size={13} /> Returns
            </Button>
          </div>
        </div>
        {showReturns ? <ReturnsPanel onClose={() => setShowReturns(false)} /> : null}

        <div className="pos-lines">
          {lines.length === 0 ? (
            <div className="empty-state">Cart is empty. Scan, search, or add an item on the right.</div>
          ) : (
            lines.map((line, i) => (
              <div
                key={i}
                className={`pos-line${selected === i ? " selected" : ""}`}
                onClick={() => selectLine(i)}
              >
                <div className="pos-line-main">
                  <span className="pos-line-desc">{line.description}</span>
                  <span className="pos-line-amount">${(lineTotalCents(line) / 100).toFixed(2)}</span>
                </div>
                <div className="pos-line-sub">
                  {line.quantity} × ${(line.unit_price_cents / 100).toFixed(2)}
                  {line.discount_bp > 0 ? (
                    <Badge tone="accent">{`-${(line.discount_bp / 100).toFixed(0)}%`}</Badge>
                  ) : null}
                  {line.product_id ? <Icon name="box" size={11} /> : null}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="pos-totals">
          <div className="pos-totals-row">
            <span>Subtotal</span>
            <span>${(totals.subtotal / 100).toFixed(2)}</span>
          </div>
          <div className="pos-totals-row">
            <span>Tax ({TAX_RATE_BP / 100}%)</span>
            <span>${(totals.tax / 100).toFixed(2)}</span>
          </div>
          <div className="pos-totals-row pos-total-main">
            <span>Total</span>
            <span>${(totals.total / 100).toFixed(2)}</span>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {lastSale ? (
          <div className="field-label">
            Last sale: ${(lastSale.amount_cents / 100).toFixed(2)} via {lastSale.method}
          </div>
        ) : null}

        <div className="pos-pay-row">
          <Button variant="secondary" disabled={lines.length === 0} onClick={() => checkout("cash")}>
            Cash
          </Button>
          <Button variant="primary" disabled={lines.length === 0} onClick={() => checkout("card")}>
            Charge
          </Button>
        </div>
      </div>

      <div className="pos-entry-pane">
        {scanNotice ? <div className="pos-scan-notice">
          <Icon name="barcode" size={14} /> {scanNotice}
        </div> : null}

        <div className="card card-padded pos-add-card">
          <div className="field-label" style={{ marginBottom: 8 }}>
            <Icon name="barcode" size={13} /> Scan a barcode, or search the catalog
          </div>
          <div style={{ position: "relative" }}>
            <Input
              placeholder="Search products by name or SKU..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {searchResults.length > 0 ? (
              <div className="pos-search-results">
                {searchResults.map((p) => (
                  <button key={p.id} className="pos-search-row" onClick={() => addFromCatalog(p)}>
                    <span>{p.name}</span>
                    <span className="field-label">
                      ${(p.price_cents / 100).toFixed(2)}
                      {p.track_inventory ? ` · ${p.on_hand_qty} on hand` : ""}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          {products.length === 0 ? (
            <div className="field-label" style={{ marginTop: 8 }}>
              No product catalog yet -- install Inventory, or add items below.
            </div>
          ) : null}
        </div>

        <div className="card card-padded pos-add-card">
          <div className="field-label" style={{ marginBottom: 8 }}>
            New freeform item
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Input
              placeholder="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <Input
              placeholder="Price"
              type="number"
              step="0.01"
              style={{ width: 110 }}
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addLine()}
            />
            <Button onClick={addLine}>
              <Icon name="plus" size={14} /> Add
            </Button>
          </div>
        </div>

        <div className="pos-numpad-wrap">
          <div className="pos-mode-toggle">
            <Button
              size="sm"
              variant={mode === "qty" ? "primary" : "secondary"}
              onClick={() => {
                setMode("qty");
                setBuffer("");
              }}
              disabled={selected === null}
            >
              Qty
            </Button>
            <Button
              size="sm"
              variant={mode === "price" ? "primary" : "secondary"}
              onClick={() => {
                setMode("price");
                setBuffer("");
              }}
              disabled={selected === null}
            >
              Price
            </Button>
            <Button
              size="sm"
              variant={mode === "discount" ? "primary" : "secondary"}
              onClick={() => {
                setMode("discount");
                setBuffer("");
              }}
              disabled={selected === null}
            >
              <Icon name="percent" size={12} /> Disc
            </Button>
            <Button size="sm" variant="danger" onClick={removeSelected} disabled={selected === null}>
              Remove
            </Button>
          </div>
          <div className="pos-numpad">
            {NUMPAD_KEYS.map((key) => (
              <button
                key={key}
                className="pos-numpad-key"
                disabled={selected === null}
                onClick={() => pressKey(key)}
              >
                {key}
              </button>
            ))}
            <button className="pos-numpad-key pos-numpad-backspace" disabled={selected === null} onClick={backspace}>
              ⌫
            </button>
          </div>
          <div className="field-label" style={{ textAlign: "center" }}>
            {selected === null
              ? "Select a line to edit its quantity or price"
              : mode === "discount"
                ? "Editing discount (% off)"
                : `Editing ${mode}`}
          </div>
        </div>
      </div>
    </div>
  );
}
