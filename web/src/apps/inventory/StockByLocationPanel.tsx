import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Card } from "../../ui/Card";

interface Level {
  warehouse_id: string | null;
  warehouse: string;
  qty: string | number;
}

/** How many of a product are at each warehouse (from the stock ledger);
 * people limited to their locations see only theirs. Hidden on an older
 * Inventory that doesn't have it. */
export function StockByLocationPanel({ productId }: { productId: string }) {
  const [levels, setLevels] = useState<Level[] | null>(null);

  useEffect(() => {
    api
      .get<Level[]>(`/api/inventory/products/${productId}/stock-by-location`)
      .then(setLevels)
      .catch(() => setLevels(null));
  }, [productId]);

  if (!levels || levels.length < 2) return null; // one place: the total says it all
  return (
    <Card style={{ marginTop: 12 }}>
      <div className="field-label" style={{ marginBottom: 8 }}>
        Stock by location
      </div>
      <table className="table" style={{ width: "100%" }}>
        <tbody>
          {levels.map((l) => (
            <tr key={l.warehouse_id ?? "none"}>
              <td>{l.warehouse}</td>
              <td style={{ textAlign: "right", color: Number(l.qty) < 0 ? "var(--danger, #c0392b)" : undefined }}>
                {Number(l.qty)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
