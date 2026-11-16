import { useEffect, useMemo, useRef, useState } from "react";
import init, { PosCart, PosOfflineQueue } from "./engine/friday_pos_engine";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fetchProductCatalog, type Product } from "../../lib/inventory";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import type { PosRegister, PosShift } from "../../lib/posApi";
import { pollPosSaleStatus, startPesapalPosPayment } from "../../lib/pos";
import { useBarcodeScanner } from "../../lib/useBarcodeScanner";
import { Avatar } from "../../ui/Avatar";
import { Icon } from "../../ui/Icon";
import { initials } from "../../ui/resource/fieldFormat";
import { chooseSerialDrawer, drawerMode, openDrawer, serialSupported, setDrawerMode, type DrawerMode } from "./drawer";
import { PosNumpad } from "./PosNumpad";
import { PosPayment, type Tender } from "./PosPayment";
import { printReceipt } from "./receipt";
import { BuyerPin, type Buyer } from "./BuyerPin";
import { lineTotalCents, tillTotals } from "./tax";
import { fmtQty, unitLabel, useUnits } from "../../lib/units";
import { ProductTile, VariantPicker } from "./ProductTile";
import { ProductEditor } from "../inventory/ProductEditor";
import { ReturnsPanel } from "./ReturnsPanel";
import { categoryTint } from "../../lib/productImages";

interface CartLine {
  description: string;
  quantity: number;
  unit_price_cents: number;
  product_id: string | null;
  discount_bp: number;
  unit_cost_cents: number | null;
}


interface Sale {
  client_sale_id: string;
  lines: (CartLine & { [extra: string]: unknown })[];
  currency: string;
  method: string;
  amount_cents: number;
  created_at_ms: number;
  payments?: { method: string; amount_cents: number }[];
  shift_id?: string;
  buyer_pin?: string;
  buyer_name?: string;
  prices_include_tax?: boolean;
}

type ShelfProduct = Product;

const QUEUE_STORAGE_KEY = "friday.pos.offline_queue";

/** The selling screen (owner's reference, 2026-11-15): the order with its
 * keypad on the left, the shelf on the right, payment full-screen. All
 * money maths stays in pos-engine (Rust/WASM); this is the register
 * around it. Sales carry the open shift, so each till's drawer count is
 * its own. */
export function PosPage({
  register,
  shift,
  onCloseRegister,
  onSwitchTill,
  onClockOut,
  onSwitchCashier,
  onPinSettings,
  onPendingChange,
}: {
  register: PosRegister | null;
  shift: PosShift;
  onCloseRegister: () => void;
  onSwitchTill: () => void;
  onClockOut: () => void;
  onSwitchCashier: () => void;
  onPinSettings: () => void;
  onPendingChange: (n: number) => void;
}) {
  const { session } = useAuth();
  const settings = useOrgSettings();
  const inclusive = settings.prices_include_tax;
  // VAT is worked out per line here (tax.ts), by each product's tax type;
  // the engine keeps the order and its discounts.
  const engineRate = 0;

  const [ready, setReady] = useState(false);
  const cartRef = useRef<PosCart | null>(null);
  const queueRef = useRef<PosOfflineQueue | null>(null);
  const [lines, setLines] = useState<CartLine[]>([]);
  const [buyer, setBuyer] = useState<Buyer | null>(null);
  // Units: a product is sold in its sales unit (a kilo, a crate); stock
  // comes off in base units (sales_factor each).
  const { byId: unitById } = useUnits();
  const salesUnitOf = (p: Product | undefined) => (p ? unitById.get(p.sales_uom_id ?? "") : undefined);
  const [products, setProducts] = useState<ShelfProduct[]>([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<"qty" | "discount" | "price">("qty");
  const [buffer, setBuffer] = useState("");
  const [view, setView] = useState<"order" | "returns">("order");
  const [paying, setPaying] = useState(false);
  const [paid, setPaid] = useState<{ change: number; total: number; drawer: string } | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customPrice, setCustomPrice] = useState("");
  const [drawer, setDrawer] = useState<DrawerMode>(drawerMode());
  const [pesapalFlow, setPesapalFlow] = useState<{ invoiceId: string; status: "starting" | "pending" | "paid" | "void" } | null>(null);

  useEffect(() => {
    init().then(() => {
      const stored = localStorage.getItem(QUEUE_STORAGE_KEY);
      queueRef.current = stored ? PosOfflineQueue.restore_json(stored) : new PosOfflineQueue();
      setPendingCount(queueRef.current.len());
      setReady(true);
    });
    fetchProductCatalog().then((p) => setProducts(p as ShelfProduct[]));
  }, []);

  // The cart follows the org's tax rule; when the settings arrive the
  // order is carried over into a cart with the right rate.
  useEffect(() => {
    if (!ready) return;
    const old = cartRef.current ? (JSON.parse(cartRef.current.lines_json()) as CartLine[]) : [];
    cartRef.current = new PosCart(BigInt(engineRate));
    rebuildCart(old);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, engineRate]);

  useEffect(() => onPendingChange(pendingCount), [pendingCount, onPendingChange]);

  function refreshCart() {
    const cart = cartRef.current;
    if (!cart) return;
    setLines(JSON.parse(cart.lines_json()));
  }

  /** pos-engine has append/remove/clear only, so editing a line rebuilds
   * the cart and reapplies each line's discount. */
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

  function flash(text: string) {
    setNotice(text);
    setTimeout(() => setNotice(null), 2500);
  }

  function addProduct(product: Product) {
    const cart = cartRef.current;
    if (!cart) return;
    // Tapping a product already in the order adds one more of it.
    const i = lines.findIndex((l) => l.product_id === product.id && l.discount_bp === 0);
    if (i >= 0) {
      rebuildCart(lines.map((l, j) => (j === i ? { ...l, quantity: l.quantity + 1 } : l)));
      setSelected(i);
    } else {
      // Cost is kept per base unit; the line is per sales unit.
      const unitCost = product.cost_cents ? Math.round(product.cost_cents * (product.sales_factor ?? 1)) : 0;
      cart.add_line(product.name, 1, BigInt(product.price_cents), product.id, unitCost ? BigInt(unitCost) : undefined);
      refreshCart();
      setSelected(lines.length);
    }
    setMode("qty");
    setBuffer("");
  }

  function addCustom() {
    const cart = cartRef.current;
    const price = Math.round(Number.parseFloat(customPrice || "0") * 100);
    if (!cart || !customName.trim() || !Number.isFinite(price) || price <= 0) return;
    cart.add_line(customName.trim(), 1, BigInt(price), undefined, undefined);
    refreshCart();
    setSelected(lines.length);
    setCustomName("");
    setCustomPrice("");
    setCustomOpen(false);
  }

  function applyBuffer(next: string) {
    setBuffer(next);
    if (selected === null) return;
    const parsed = next === "" || next === "." ? 0 : Number.parseFloat(next);
    const value = Number.isFinite(parsed) ? parsed : 0;
    if (mode === "discount") {
      const pct = Math.min(Math.max(value, 0), 100);
      cartRef.current?.set_line_discount_bp(selected, BigInt(next === "" ? 0 : Math.round(pct * 100)));
      refreshCart();
      return;
    }
    rebuildCart(
      lines.map((l, i) => {
        if (i !== selected) return l;
        if (mode === "qty") return { ...l, quantity: next === "" ? l.quantity : value };
        return { ...l, unit_price_cents: next === "" ? l.unit_price_cents : Math.round(value * 100) };
      }),
    );
  }

  function pressKey(key: string) {
    if (selected === null) return;
    if (key === "+/-") {
      flash("Returns go through Orders & returns");
      return;
    }
    if (key === "." && buffer.includes(".")) return;
    applyBuffer(buffer + key);
  }

  function backspace() {
    if (selected === null) return;
    if (buffer === "" && mode === "qty") {
      // Backspace on an untouched line removes it, as on a counter register.
      cartRef.current?.remove_line(selected);
      setSelected(lines.length > 1 ? Math.max(0, selected - 1) : null);
      refreshCart();
      return;
    }
    applyBuffer(buffer.slice(0, -1));
  }

  useBarcodeScanner((code) => {
    const match = products.find((p) => p.barcode && p.barcode === code);
    if (match) {
      addProduct(match);
      flash(`Scanned: ${match.name}`);
    } else {
      flash(`No product with barcode ${code}`);
    }
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
        if (!(err instanceof ApiError) || err.status === 0) break; // offline: try the rest later
      }
    }
    setSyncing(false);
  }

  useEffect(() => {
    if (!ready) return;
    syncPending();
    const onOnline = () => syncPending();
    window.addEventListener("online", onOnline);
    const t = setInterval(syncPending, 30_000);
    return () => {
      window.removeEventListener("online", onOnline);
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  /** What the engine's sale doesn't know: each line's tax type, VAT and
   * eTIMS item details, the total with VAT, and the buyer's KRA PIN. */
  function annotate(sale: Sale): Sale {
    const t = tillTotals(sale.lines, (id) => (id ? byId.get(id)?.tax_code ?? "" : ""), settings);
    const out: Sale = {
      ...sale,
      amount_cents: t.total,
      prices_include_tax: inclusive,
      lines: sale.lines.map((l, i) => {
        const p = l.product_id ? byId.get(l.product_id) : undefined;
        const sold = salesUnitOf(p);
        const baseUnit = p ? unitById.get(p.base_uom_id ?? "") : undefined;
        const factor = p?.sales_factor ?? 1;
        // eTIMS: the sold unit's KRA code, else the base unit's (with the
        // quantity in base units), else pieces.
        const kra = sold?.etims_code
          ? { etims_quantity_unit: sold.etims_code }
          : baseUnit?.etims_code
            ? { etims_quantity_unit: baseUnit.etims_code, etims_qty_factor: factor }
            : {};
        return {
          ...l,
          ...(p ? { uom: unitLabel(sold), uom_factor: factor, ...kra } : {}),
          tax_code: t.lines[i].code,
          vat_cents: t.lines[i].vat_cents,
          ...(p?.etims_item_code ? { etims_item_code: p.etims_item_code } : {}),
          ...(p?.etims_item_class ? { etims_item_class: p.etims_item_class } : {}),
          ...(p?.etims_packaging_unit ? { etims_packaging_unit: p.etims_packaging_unit } : {}),
        };
      }),
    };
    if (buyer?.pin) {
      out.buyer_pin = buyer.pin;
      out.buyer_name = buyer.name;
    }
    return out;
  }

  async function onPaid(tenders: Tender[], change: number) {
    const cart = cartRef.current;
    const queue = queueRef.current;
    if (!cart || !queue || lines.length === 0) return;
    setError(null);
    let saleJson: string;
    try {
      const method = tenders.length === 1 ? tenders[0].method : "split";
      const payments =
        tenders.length > 1 ? JSON.stringify(tenders.map((t) => ({ method: t.method, amount_cents: t.cents }))) : undefined;
      saleJson = cart.checkout_json(settings.currency, method, Date.now(), payments);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the sale");
      return;
    }
    const sale: Sale = annotate({ ...JSON.parse(saleJson), shift_id: shift.id });
    queue.enqueue_json(JSON.stringify(sale));
    persistQueue();

    const soldLines = lines;
    const total = totals.total;
    const tax = totals.tax;
    cart.clear();
    setSelected(null);
    setBuffer("");
    refreshCart();
    setPaying(false);
    setBuyer(null);

    // The drawer opens for cash only. A direct (serial) drawer opens now;
    // with the printer's driver doing it, printing the receipt opens it.
    let drawerNote = "";
    const hasCash = tenders.some((t) => t.method === "cash") || change > 0;
    if (hasCash) {
      try {
        const kicked = await openDrawer();
        drawerNote = kicked ? "Drawer open" : drawer === "printer" ? "Drawer opens with the receipt" : "";
      } catch (err) {
        drawerNote = err instanceof Error ? err.message : "The drawer didn't open";
      }
    }
    setPaid({ change, total, drawer: drawerNote });
    if (hasCash && drawer === "printer") {
      printReceipt({
        businessName: settings.name,
        registerName: register?.name ?? "Till",
        cashier: session?.email ?? "",
        number: sale.client_sale_id.slice(0, 8).toUpperCase(),
        at: new Date(),
        lines: soldLines.map((l) => ({ description: l.description, quantity: l.quantity, totalCents: lineTotalCents(l) })),
        totalCents: total,
        taxCents: tax,
        taxLabel,
        payments: tenders.map((t) => ({ method: t.method, cents: t.method === "cash" ? t.cents + change : t.cents })),
        changeCents: change,
        currency: settings.currency,
        taxPin: settings.tax?.receipt_show_pin ? settings.tax.tax_pin : "",
        buyerPin: buyer?.pin,
        buyerName: buyer?.name,
        taxLines: totals.byCode
          .filter((c) => c.rate_bp > 0 || totals.byCode.length > 1)
          .map((c) => ({ label: `${c.code} ${c.name} ${c.rate_bp / 100}%`, cents: c.vat_cents })),
        showTax: settings.tax ? settings.tax.vat_registered && settings.tax.receipt_show_breakdown : true,
        footer: settings.tax?.receipt_footer,
      });
    }

    try {
      await api.post("/api/invoicing/pos/sales", sale);
      queue.mark_synced(sale.client_sale_id);
      persistQueue();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status !== 0
          ? `Sale saved on this till; sending it failed: ${err.message}`
          : "Sale saved on this till; it sends when back online.",
      );
    }
  }

  async function payWithPesapal() {
    const cart = cartRef.current;
    if (!cart || lines.length === 0) return;
    setError(null);
    let sale: Sale;
    try {
      sale = annotate({ ...JSON.parse(cart.checkout_json(settings.currency, "pesapal", Date.now())), shift_id: shift.id });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the sale");
      return;
    }
    setPaying(false);
    setPesapalFlow({ invoiceId: "", status: "starting" });
    try {
      const { invoice_id, redirect_url } = await startPesapalPosPayment(sale);
      setPesapalFlow({ invoiceId: invoice_id, status: "pending" });
      window.open(redirect_url, "_blank", "noopener");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start Pesapal checkout");
      setPesapalFlow(null);
    }
  }

  useEffect(() => {
    if (!pesapalFlow || pesapalFlow.status !== "pending") return;
    const interval = setInterval(async () => {
      try {
        const result = await pollPosSaleStatus(pesapalFlow.invoiceId);
        if (result.status === "paid") {
          cartRef.current?.clear();
          setSelected(null);
          refreshCart();
          setPesapalFlow((cur) => (cur ? { ...cur, status: "paid" } : cur));
        } else if (result.status === "void") {
          setPesapalFlow((cur) => (cur ? { ...cur, status: "void" } : cur));
        }
      } catch {
        // keep polling
      }
    }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pesapalFlow?.invoiceId, pesapalFlow?.status]);

  // Variants hang off their main product; the shelf shows one tile for
  // the main product and asks which. A variant takes its main product's
  // category when it has none of its own.
  const variantsOf = useMemo(() => {
    const m = new Map<string, ShelfProduct[]>();
    for (const p of products) {
      if (p.variant_of) m.set(p.variant_of, [...(m.get(p.variant_of) ?? []), p]);
    }
    for (const list of m.values()) list.sort((a, b) => a.price_cents - b.price_cents);
    return m;
  }, [products]);
  const byId = useMemo(() => new Map(products.map((p) => [p.id, p])), [products]);
  const totals = useMemo(
    () => tillTotals(lines, (id) => (id ? byId.get(id)?.tax_code ?? "" : ""), settings),
    [lines, byId, settings],
  );
  const registered = settings.tax ? settings.tax.vat_registered : true;
  const taxLabel = !registered
    ? "No VAT (not registered)"
    : totals.byCode.filter((c) => c.rate_bp > 0).length > 1
      ? `VAT${inclusive ? " (included)" : ""}`
      : `VAT ${(totals.byCode.find((c) => c.rate_bp > 0)?.rate_bp ?? settings.tax_rate_bp) / 100}%${inclusive ? " (included)" : ""}`;
  const categoryOf = (p: ShelfProduct) =>
    (p.category?.trim() || (p.variant_of ? byId.get(p.variant_of)?.category?.trim() : "") || "").trim();
  const categories = useMemo(
    () => [...new Set(products.map(categoryOf).filter((c) => !!c))].sort(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [products, byId],
  );
  const inCart = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of lines) {
      if (!l.product_id) continue;
      m.set(l.product_id, (m.get(l.product_id) ?? 0) + l.quantity);
      const parent = byId.get(l.product_id)?.variant_of;
      if (parent) m.set(parent, (m.get(parent) ?? 0) + l.quantity);
    }
    return m;
  }, [lines, byId]);
  const shelf = useMemo(() => {
    const q = search.trim().toLowerCase();
    return products.filter((p) => {
      if (category && categoryOf(p) !== category) return false;
      if (!q) return !p.variant_of; // browsing: main products only
      // Searching: every match, variants included (a scan names one).
      if (variantsOf.has(p.id)) return false;
      return p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || p.barcode === q;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [products, search, category, variantsOf]);
  const [choosing, setChoosing] = useState<ShelfProduct | null>(null);
  // Owners and admins can add a product (photo, variants) from the till.
  const canManageProducts = session?.role === "owner" || session?.role === "admin";
  const [newProduct, setNewProduct] = useState(false);

  if (!ready) {
    return (
      <div className="till-stage">
        <div />
        <div className="till-stage-center till-text">Starting the register…</div>
        <div />
      </div>
    );
  }

  if (paying) {
    return (
      <PosPayment
        totalCents={totals.total}
        taxCents={totals.tax}
        taxLabel={taxLabel}
        pesapal={payWithPesapal}
        onCancel={() => setPaying(false)}
        onPaid={onPaid}
        buyer={<BuyerPin value={buyer} onChange={setBuyer} />}
      />
    );
  }

  if (paid) {
    return (
      <div className="till-stage">
        <div />
        <div className="till-stage-center">
          <div className="till-panel glass" style={{ textAlign: "center" }}>
            <div className="till-text">Paid {formatMoney(paid.total)}</div>
            {paid.change > 0 ? (
              <>
                <div className="till-text" style={{ marginTop: 8 }}>
                  Give change
                </div>
                <div className="till-change">{formatMoney(paid.change)}</div>
              </>
            ) : (
              <div className="till-change" style={{ fontSize: 40 }}>
                Thank you
              </div>
            )}
            {paid.drawer ? (
              <div className="till-chip ok" style={{ justifySelf: "center" }}>
                {paid.drawer}
              </div>
            ) : null}
            {error ? (
              <div className="till-error" style={{ margin: 0 }}>
                {error}
              </div>
            ) : null}
            <div className="till-panel-actions">
              <button
                type="button"
                className="till-btn"
                onClick={() => openDrawer().catch((e) => flash(e instanceof Error ? e.message : "The drawer didn't open"))}
                disabled={drawer !== "serial"}
                title={drawer === "serial" ? "" : "Set up a direct drawer in the till menu"}
              >
                Open drawer
              </button>
              <button type="button" className="till-btn primary" autoFocus onClick={() => (setPaid(null), setError(null))}>
                New order
              </button>
            </div>
          </div>
        </div>
        <div />
        {notice ? <div className="till-notice glass">{notice}</div> : null}
      </div>
    );
  }

  const sel = selected !== null ? lines[selected] : null;
  return (
    <div className="till">
      <header className="till-bar">
        <div className="till-tabs glass">
          <button type="button" className={`till-tab${view === "order" ? " active" : ""}`} onClick={() => setView("order")}>
            Register
          </button>
          <button type="button" className={`till-tab${view === "returns" ? " active" : ""}`} onClick={() => setView("returns")}>
            Orders &amp; returns
          </button>
        </div>
        <span className="till-chip glass">
          {register?.name ?? "Main till"}
          {register?.location_name ? ` · ${register.location_name}` : ""}
        </span>
        {pendingCount > 0 ? (
          <button type="button" className="till-chip warn" style={{ border: 0, cursor: "pointer" }} onClick={syncPending}>
            {syncing ? "Sending…" : `${pendingCount} waiting to send`}
          </button>
        ) : (
          <span className="till-chip ok">All sent</span>
        )}
        <label className="till-search">
          <Icon name="search" size={18} />
          <input placeholder="Search or scan a product…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <button type="button" className="till-user" onClick={() => setMenuOpen((o) => !o)} aria-haspopup="menu" aria-label="Till menu">
          <Avatar label={initials(session?.email ?? "")} title={session?.email ?? ""} size={34} />
          <span style={{ fontSize: 22, lineHeight: 1 }}>☰</span>
        </button>
        {menuOpen ? (
          <div className="till-menu glass" role="menu" onMouseLeave={() => setMenuOpen(false)}>
            <div className="till-text" style={{ padding: "8px 12px" }}>
              {session?.email}
            </div>
            <button type="button" onClick={() => (setMenuOpen(false), onCloseRegister())}>
              <Icon name="calculator" size={18} /> Close register
            </button>
            <button type="button" onClick={() => (setMenuOpen(false), onSwitchTill())}>
              <Icon name="storefront" size={18} /> Switch till
            </button>
            <button type="button" onClick={() => (setMenuOpen(false), onSwitchCashier())}>
              <Icon name="users" size={18} /> Switch cashier
            </button>
            <button type="button" onClick={() => (setMenuOpen(false), onPinSettings())}>
              <Icon name="shield-check" size={18} /> Cashier PIN
            </button>
            <div className="till-text" style={{ padding: "8px 12px 2px" }}>
              Cash drawer
            </div>
            {(["printer", "serial", "none"] as DrawerMode[]).map((m) => (
              <button
                key={m}
                type="button"
                disabled={m === "serial" && !serialSupported()}
                onClick={async () => {
                  if (m === "serial") {
                    try {
                      await chooseSerialDrawer();
                    } catch (e) {
                      flash(e instanceof Error ? e.message : "No port chosen");
                      return;
                    }
                  }
                  setDrawerMode(m);
                  setDrawer(m);
                }}
              >
                {drawer === m ? "●" : "○"}{" "}
                {m === "printer" ? "Opens when the receipt prints" : m === "serial" ? "Direct (USB / serial port)" : "No drawer"}
              </button>
            ))}
            <button type="button" onClick={() => (setMenuOpen(false), onClockOut())}>
              <Icon name="logout" size={18} /> Clock out
            </button>
          </div>
        ) : null}
      </header>

      {view === "returns" ? (
        <div style={{ padding: 24, overflow: "auto" }}>
          <ReturnsPanel shiftId={shift.id} onClose={() => setView("order")} />
        </div>
      ) : (
        <div className="till-body">
          <section className="till-order" aria-label="Order">
            <div className="till-lines">
              {lines.length === 0 ? (
                <div className="till-empty">Scan a barcode or tap a product to start an order.</div>
              ) : (
                lines.map((line, i) => (
                  <div
                    key={i}
                    className={`till-line${selected === i ? " selected" : ""}`}
                    onClick={() => (setSelected(i), setBuffer(""))}
                  >
                    <span className="till-line-name">{line.description}</span>
                    <span className="till-line-amount">{formatMoney(lineTotalCents(line))}</span>
                    <span className="till-line-sub">
                      <b>{fmtQty(line.quantity)}</b>
                      {(() => {
                        const u = unitLabel(salesUnitOf(line.product_id ? byId.get(line.product_id) : undefined));
                        return u && u !== "pc" ? ` ${u}` : "";
                      })()}{" "}
                      × {formatMoney(line.unit_price_cents)}
                      {line.discount_bp > 0 ? ` · ${line.discount_bp / 100}% off` : ""}
                    </span>
                  </div>
                ))
              )}
            </div>
            <div className="till-totals">
              <div className="till-totals-row">
                <span>{taxLabel}</span>
                <span>{formatMoney(totals.tax)}</span>
              </div>
              <div className="till-total">
                <span>Total</span>
                <span>{formatMoney(totals.total)}</span>
              </div>
            </div>
            {error ? <div className="till-error">{error}</div> : null}
            {pesapalFlow ? (
              <div className="till-error" style={{ background: "rgba(224,122,53,.12)", color: "#9a4a12" }}>
                {pesapalFlow.status === "starting" && "Starting Pesapal checkout…"}
                {pesapalFlow.status === "pending" && "Waiting for the customer to pay on Pesapal…"}
                {pesapalFlow.status === "paid" && "Pesapal payment received."}
                {pesapalFlow.status === "void" && "Pesapal payment failed or was cancelled."}
                {pesapalFlow.status === "paid" || pesapalFlow.status === "void" ? (
                  <button type="button" onClick={() => setPesapalFlow(null)} style={{ marginLeft: 8 }}>
                    OK
                  </button>
                ) : null}
              </div>
            ) : null}
            <div className="till-hint">
              {sel
                ? mode === "qty"
                  ? `Quantity of ${sel.description} · ⌫ removes the line`
                  : mode === "price"
                    ? `New price for ${sel.description}`
                    : `Discount on ${sel.description} (% off)`
                : "Tap a line to change its quantity, price or discount"}
            </div>
            <PosNumpad
              onKey={pressKey}
              onBackspace={backspace}
              modes={[
                { id: "qty", label: "Qty" },
                { id: "discount", label: "%" },
                { id: "price", label: "Price" },
              ]}
              activeMode={mode}
              onMode={(m) => (setMode(m as typeof mode), setBuffer(""))}
              disabled={selected === null}
              allowSign
            />
            <button type="button" className="till-pay" disabled={lines.length === 0} onClick={() => setPaying(true)}>
              <span>Payment</span>
              <span>{formatMoney(totals.total)}</span>
            </button>
          </section>

          <section className="till-shelf" aria-label="Products">
            <div className="till-cats">
              <button type="button" className={`till-cat glass${category === "" ? " active" : ""}`} onClick={() => setCategory("")}>
                All
              </button>
              {categories.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`till-cat glass${category === c ? " active" : ""}`}
                  style={{ ["--cat-bar" as string]: categoryTint(c, categories).bar, ["--cat-soft" as string]: categoryTint(c, categories).soft }}
                  onClick={() => setCategory(category === c ? "" : c)}
                >
                  {c}
                </button>
              ))}
            </div>
            <div className="till-grid">
              {shelf.map((p) => {
                const variants = variantsOf.get(p.id) ?? [];
                return (
                  <ProductTile
                    key={p.id}
                    product={p}
                    category={categoryOf(p)}
                    categories={categories}
                    count={inCart.get(p.id) ?? 0}
                    variants={variants}
                    onPick={() => (variants.length ? setChoosing(p) : addProduct(p))}
                  />
                );
              })}
              {canManageProducts ? (
                <button type="button" className="till-tile add glass" onClick={() => setNewProduct(true)}>
                  + New product
                </button>
              ) : null}
              {customOpen ? (
                <div className="till-tile glass" style={{ gridColumn: "span 2", gap: 8 }}>
                  <input className="till-input" placeholder="Item" value={customName} onChange={(e) => setCustomName(e.target.value)} autoFocus />
                  <div style={{ display: "flex", gap: 8 }}>
                    <input
                      className="till-input"
                      placeholder="Price"
                      inputMode="decimal"
                      value={customPrice}
                      onChange={(e) => setCustomPrice(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && addCustom()}
                      style={{ flex: 1, minWidth: 0 }}
                    />
                    <button type="button" className="till-btn primary" style={{ flex: "none", width: 90, height: 48 }} onClick={addCustom}>
                      Add
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className="till-tile add glass" onClick={() => setCustomOpen(true)}>
                  + Item not on the shelf
                </button>
              )}
              {products.length === 0 ? (
                <div className="till-empty" style={{ gridColumn: "1 / -1" }}>
                  No products yet. Add them in Inventory, or import a list (Settings → Import).
                </div>
              ) : null}
            </div>
          </section>
        </div>
      )}
      {newProduct ? (
        <ProductEditor
          all={products}
          onClose={() => setNewProduct(false)}
          onSaved={(changed) => {
            const got = changed as unknown as ShelfProduct[];
            setProducts((cur) => [...got.filter((g) => !cur.some((c) => c.id === g.id)), ...cur.map((c) => got.find((g) => g.id === c.id) ?? c)]);
            flash(`Added ${got[0]?.name ?? "the product"}`);
          }}
        />
      ) : null}
      {choosing ? (
        <VariantPicker
          product={choosing}
          variants={variantsOf.get(choosing.id) ?? []}
          onPick={(v) => {
            addProduct({ ...v, name: v.variant_name ? `${choosing.name} ${v.variant_name}` : v.name });
            setChoosing(null);
          }}
          onClose={() => setChoosing(null)}
        />
      ) : null}
      {notice ? <div className="till-notice glass">{notice}</div> : null}
    </div>
  );
}
