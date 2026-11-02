import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { Icon } from "../../ui/Icon";

interface CreatePurchaseOrderPanelProps {
  productId: string;
  onHandQty: number;
  reorderPoint: number;
}

/** The "Create purchase order" action on a low-stock product -- same
 * targeted-special-case shape as Invoicing's PayWithCardPanel: rendered
 * by FormView only for inventory's product resource, only when the
 * product actually needs reordering, rather than a general per-resource
 * action framework. */
export function CreatePurchaseOrderPanel({ productId, onHandQty, reorderPoint }: CreatePurchaseOrderPanelProps) {
  const [status, setStatus] = useState<"idle" | "creating" | "created">("idle");
  const [poNumber, setPoNumber] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (reorderPoint <= 0 || onHandQty > reorderPoint) return null;

  async function create() {
    setStatus("creating");
    setError(null);
    try {
      const po = await api.post<{ number: string }>(`/api/inventory/purchase_orders/from-product/${productId}`);
      setPoNumber(po.number);
      setStatus("created");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create purchase order");
      setStatus("idle");
    }
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div className="field-label" style={{ marginBottom: 8 }}>
        <Icon name="history" size={13} /> On hand ({onHandQty}) is at or below the reorder point ({reorderPoint})
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {status === "created" ? (
        <div className="field-label">
          Created draft purchase order {poNumber} -- open Inventory &gt; Purchase Orders to pick a supplier and send
          it.
        </div>
      ) : (
        <Button type="button" onClick={create} disabled={status === "creating"}>
          {status === "creating" ? "Creating..." : "Create purchase order"}
        </Button>
      )}
    </Card>
  );
}
