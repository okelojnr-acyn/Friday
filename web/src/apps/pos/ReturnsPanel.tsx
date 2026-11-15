import { useState } from "react";
import { ApiError } from "../../lib/api";
import { fetchPosSale, returnPosSale, type PosSale } from "../../lib/pos";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { formatMoney } from "../../lib/orgSettings";

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
    <Modal title="Returns" onClose={onClose}>
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
