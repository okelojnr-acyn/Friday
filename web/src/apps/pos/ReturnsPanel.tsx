import { useState } from "react";
import { ApiError } from "../../lib/api";
import { fetchPosSale, returnPosSale, type PosSale } from "../../lib/pos";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { api } from "../../lib/api";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import { printReceipt, type ReceiptEtims } from "./receipt";

interface StoredReceipt {
  number: string;
  issued_at: string;
  cashier: string;
  currency: string;
  buyer_pin: string;
  buyer_name: string;
  prices_include_vat: boolean;
  lines: { description: string; quantity: number; unit: string; unit_price_cents: number; discount_bp: number; total_cents: number; tax_code: string }[];
  vat: { code: string; rate_pct: number; taxable_cents: number; vat_cents: number }[];
  vat_cents: number;
  total_cents: number;
  payments: { method: string; cents: number }[];
  etims: ReceiptEtims | null;
}

interface ReturnsPanelProps {
  onClose: () => void;
  /** The open shift, so the refund comes out of this till's count. */
  shiftId?: string;
}

/** Look up a past sale by receipt number and refund it in full. A
 * genuinely separate flow from the cart on the main register screen (a
 * return isn't "negative items in today's cart," it's "undo a specific
 * past sale"), so it's its own modal rather than a mode of PosPage's
 * cart state. */
export function ReturnsPanel({ onClose, shiftId }: ReturnsPanelProps) {
  const [number, setNumber] = useState("");
  const [sale, setSale] = useState<PosSale | null>(null);
  const [refunded, setRefunded] = useState<PosSale | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const settings = useOrgSettings();

  /** A copy of a past sale's receipt, with KRA's eTIMS details once filed. */
  async function reprint() {
    if (!sale) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<StoredReceipt>(`/api/invoicing/etims/receipt/${encodeURIComponent(sale.number)}`);
      const tax = settings.tax;
      printReceipt({
        businessName: settings.name,
        registerName: "Till",
        cashier: r.cashier,
        number: r.number,
        at: new Date(r.issued_at),
        lines: r.lines.map((l) => ({
          description: l.description,
          quantity: l.quantity,
          totalCents: l.total_cents,
          unitPriceCents: l.unit_price_cents,
          unit: l.unit || undefined,
          taxCode: l.tax_code || undefined,
          discountBp: l.discount_bp || undefined,
        })),
        totalCents: r.total_cents,
        taxCents: r.vat_cents,
        taxLabel: "VAT",
        vat: tax?.vat_registered === false ? undefined : r.vat.map((v) => ({ code: v.code, ratePct: v.rate_pct, taxableCents: v.taxable_cents, vatCents: v.vat_cents })),
        payments: r.payments,
        changeCents: 0,
        currency: r.currency,
        address: tax?.receipt_address,
        phone: tax?.receipt_phone,
        taxPin: tax?.receipt_show_pin ? tax.tax_pin : "",
        showTax: tax ? tax.vat_registered && tax.receipt_show_breakdown : true,
        footer: tax?.receipt_footer,
        pricesIncludeVat: r.prices_include_vat,
        buyerPin: r.buyer_pin || undefined,
        buyerName: r.buyer_name || undefined,
        etims: r.etims,
        reprint: true,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load that receipt");
    } finally {
      setLoading(false);
    }
  }

  async function lookup() {
    if (!number.trim()) return;
    setLoading(true);
    setError(null);
    setSale(null);
    setRefunded(null);
    try {
      setSale(await fetchPosSale(number.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not find that sale");
    } finally {
      setLoading(false);
    }
  }

  async function refund() {
    if (!sale) return;
    setLoading(true);
    setError(null);
    try {
      setRefunded(await returnPosSale(sale.number, shiftId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refund that sale");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal title="Find a sale: reprint or return" onClose={onClose}>
      {error ? <div className="error-banner">{error}</div> : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Input
          placeholder="Receipt number (e.g. POS-20261102-ABC123)"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && lookup()}
          style={{ flex: 1 }}
        />
        <Button type="button" onClick={lookup} disabled={loading}>
          <Icon name="search" size={14} /> Find
        </Button>
      </div>

      {sale ? (
        <div className="card card-padded" style={{ marginTop: 12 }}>
          <div className="pos-totals-row">
            <span>{sale.number}</span>
            <span>
              {formatMoney(sale.total_cents, { currency: sale.currency })}
            </span>
          </div>
          <div className="field-label">Status: {sale.status}</div>
          <Button type="button" onClick={reprint} disabled={loading} style={{ marginTop: 8, marginRight: 8 }}>
            Reprint receipt
          </Button>
          {refunded ? (
            <div className="field-label" style={{ marginTop: 8 }}>
              Refunded as {refunded.number} -- stock for any catalog items restocks automatically.
            </div>
          ) : sale.status === "void" ? (
            <div className="field-label" style={{ marginTop: 8 }}>
              This sale is already void.
            </div>
          ) : (
            <Button type="button" variant="danger" onClick={refund} disabled={loading} style={{ marginTop: 8 }}>
              <Icon name="history" size={14} /> Refund in full
            </Button>
          )}
        </div>
      ) : null}
    </Modal>
  );
}
