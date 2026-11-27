import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";

type OnlineOrder = {
  id: string;
  number: string;
  status: "placed" | "paid" | "ready" | "completed" | "cancelled";
  fulfilment: "pickup" | "delivery";
  total_cents: number;
  created_at: string;
  customer_name: string;
  phone: string;
  email: string;
  address: string;
  note: string;
  lines: { product_id: string | null; name: string; variant_name: string; quantity: number; unit_price_cents: number; total_cents: number }[];
};

const STATUS: Record<OnlineOrder["status"], string> = {
  placed: "Waiting for payment",
  paid: "Paid",
  ready: "Ready",
  completed: "Handed over",
  cancelled: "Cancelled",
};

/** Inventory > Online orders: orders from the online shop. A paid order
 * is got ready and handed over (collected or delivered); an unpaid one
 * can be cancelled, which frees the stock it was holding. */
export function OnlineOrdersPage() {
  const [orders, setOrders] = useState<OnlineOrder[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [method, setMethod] = useState<Record<string, string>>({});
  const { currency } = useOrgSettings();

  /** Paid at collection: booked like a till sale (Invoicing), so the
   * stock and books follow and the order turns paid. */
  async function collect(o: OnlineOrder) {
    setBusy(o.id);
    setError(null);
    try {
      await api.post("/api/invoicing/shop/collect", {
        order_id: o.id,
        number: o.number,
        total_cents: o.total_cents,
        currency,
        method: method[o.id] ?? "cash",
        lines: o.lines,
      });
      // The order turns paid when Inventory hears of the sale.
      window.setTimeout(load, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  /** Cancel and refund a paid order: the sale is returned like a till
   * return (Paystack refunds itself, cash comes out of the drawer, the
   * stock goes back), then the order is cancelled. */
  async function refund(o: OnlineOrder) {
    if (!window.confirm(`Refund ${formatMoney(o.total_cents)} and cancel ${o.number}?`)) return;
    setBusy(o.id);
    setError(null);
    try {
      await api.post(`/api/invoicing/pos/sales/WEB-${o.number}/return`, { client_return_id: `shop-${o.id}` });
      await api.post(`/api/inventory/shop_orders/${o.id}/status`, { status: "cancelled" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  function load() {
    api
      .get<OnlineOrder[]>("/api/inventory/shop_orders")
      .then(setOrders)
      .catch((err) =>
        setError(err instanceof ApiError && err.status === 404 ? "Update Friday to see online orders." : "Could not load the online orders."),
      );
  }
  useEffect(load, []);

  async function move(o: OnlineOrder, status: string) {
    setBusy(o.id);
    setError(null);
    try {
      await api.post(`/api/inventory/shop_orders/${o.id}/status`, { status });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="page-header">
        <h1 className="page-title">Online orders</h1>
      </div>
      {error ? (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      ) : null}
      {orders && orders.length === 0 ? <p className="field-label">No online orders yet.</p> : null}
      <div style={{ display: "grid", gap: 12 }}>
        {orders?.map((o) => (
          <div key={o.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 14 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "space-between", alignItems: "baseline" }}>
              <strong>
                {o.number} · {o.customer_name}
              </strong>
              <Badge tone={o.status === "paid" ? "success" : o.status === "cancelled" ? "neutral" : "accent"}>{STATUS[o.status]}</Badge>
            </div>
            <p className="field-label" style={{ margin: "4px 0" }}>
              {[o.phone, o.email].filter(Boolean).join(" · ")} · {o.fulfilment === "delivery" ? `Deliver to ${o.address}` : "Pickup"} ·{" "}
              {new Date(o.created_at).toLocaleString()}
            </p>
            <ul style={{ margin: "8px 0", paddingLeft: 18 }}>
              {o.lines.map((l, i) => (
                <li key={i}>
                  {l.quantity} × {l.name}
                  {l.variant_name ? ` (${l.variant_name})` : ""}: {formatMoney(l.total_cents)}
                </li>
              ))}
            </ul>
            {o.note ? <p style={{ margin: "4px 0" }}>Note: {o.note}</p> : null}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
              <strong style={{ marginRight: "auto" }}>{formatMoney(o.total_cents)}</strong>
              {o.status === "paid" ? (
                <Button size="sm" disabled={busy === o.id} onClick={() => move(o, "ready")}>
                  Mark ready
                </Button>
              ) : null}
              {o.status === "paid" || o.status === "ready" ? (
                <Button size="sm" variant={o.status === "ready" ? "primary" : "secondary"} disabled={busy === o.id} onClick={() => move(o, "completed")}>
                  {o.fulfilment === "delivery" ? "Delivered" : "Collected"}
                </Button>
              ) : null}
              {o.status === "paid" || o.status === "ready" ? (
                <Button size="sm" variant="secondary" disabled={busy === o.id} onClick={() => refund(o)}>
                  Cancel and refund
                </Button>
              ) : null}
              {o.status === "placed" ? (
                <>
                  <select
                    aria-label="How they paid"
                    value={method[o.id] ?? "cash"}
                    onChange={(e) => setMethod({ ...method, [o.id]: e.target.value })}
                  >
                    <option value="cash">Cash</option>
                    <option value="mpesa">M-Pesa</option>
                    <option value="card">Card</option>
                  </select>
                  <Button size="sm" disabled={busy === o.id} onClick={() => collect(o)}>
                    Paid at collection
                  </Button>
                  <Button size="sm" variant="secondary" disabled={busy === o.id} onClick={() => move(o, "cancelled")}>
                    Cancel
                  </Button>
                </>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
