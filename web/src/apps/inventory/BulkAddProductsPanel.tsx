import { useState } from "react";
import { Modal } from "../../ui/Modal";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Input, Select } from "../../ui/Field";
import { amountInputToCents } from "../../ui/resource/fieldFormat";
import { bulkCreateProducts, type ProductBulkRow } from "../../lib/inventory";
import { invalidateReferenceOptions } from "../../lib/referenceCache";
import { useBarcodeScanner } from "../../lib/useBarcodeScanner";
import { ApiError } from "../../lib/api";
import type { RecordRow } from "../../lib/types";

interface Row {
  key: number;
  kind: "product" | "service";
  name: string;
  barcode: string;
  sku: string;
  price: string;
  cost: string;
  qty: string;
}

let nextKey = 1;

function emptyRow(kind: Row["kind"] = "product", barcode = ""): Row {
  return { key: nextKey++, kind, name: "", barcode, sku: "", price: "", cost: "", qty: "" };
}

interface BulkAddProductsPanelProps {
  onClose: () => void;
  onSaved: (records: RecordRow[]) => void;
}

/** Scan a run of barcodes (or just click "Add row" for a service that
 * has none), fill in name/price per row, save all in one request --
 * apps/inventory/app/main.py's bulk_create_products. Separate from the
 * generic "New" button's single-record FormView the same way Invoicing's
 * "New Invoice" is: a flat field list doesn't fit "receive a box of ten
 * different items at once." */
export function BulkAddProductsPanel({ onClose, onSaved }: BulkAddProductsPanelProps) {
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [scanNotice, setScanNotice] = useState<string | null>(null);

  useBarcodeScanner((code) => {
    setRows((cur) => [...cur, emptyRow("product", code)]);
    setScanNotice(`Scanned ${code} -- fill in a name and price below`);
    setTimeout(() => setScanNotice(null), 2500);
  });

  function updateRow(key: number, patch: Partial<Row>) {
    setRows((cur) => cur.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((cur) => [...cur, emptyRow()]);
  }

  function removeRow(key: number) {
    setRows((cur) => (cur.length > 1 ? cur.filter((r) => r.key !== key) : cur));
  }

  async function onSubmit() {
    const validRows = rows.filter((r) => r.name.trim());
    if (validRows.length === 0) {
      setError("Add at least one row with a name");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const products: ProductBulkRow[] = validRows.map((r) => ({
        name: r.name.trim(),
        kind: r.kind,
        sku: r.sku.trim(),
        barcode: r.barcode.trim(),
        price_cents: amountInputToCents(r.price || "0"),
        cost_cents: amountInputToCents(r.cost || "0"),
        on_hand_qty: r.kind === "service" ? 0 : Number(r.qty) || 0,
        track_inventory: r.kind === "product",
      }));
      const saved = await bulkCreateProducts(products);
      invalidateReferenceOptions("inventory", "product");
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create these products");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="Bulk Add Products"
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" variant="primary" onClick={onSubmit} disabled={submitting}>
            {submitting ? "Creating..." : `Create ${rows.filter((r) => r.name.trim()).length || ""} items`}
          </Button>
        </>
      }
    >
      {error ? <div className="error-banner">{error}</div> : null}
      <div className="field-label" style={{ marginBottom: 8 }}>
        <Icon name="barcode" size={13} /> Scan a barcode to add a row, or add one by hand for a service
      </div>
      {scanNotice ? <div className="pos-scan-notice">{scanNotice}</div> : null}

      <div className="invoice-lines">
        {rows.map((row) => (
          <div className="invoice-line-row" key={row.key}>
            <Select
              value={row.kind}
              onChange={(e) => updateRow(row.key, { kind: e.target.value as Row["kind"] })}
              style={{ width: 90 }}
            >
              <option value="product">Product</option>
              <option value="service">Service</option>
            </Select>
            <Input
              placeholder="Name"
              value={row.name}
              onChange={(e) => updateRow(row.key, { name: e.target.value })}
              style={{ flex: 1 }}
            />
            {row.kind === "product" ? (
              <Input
                placeholder="Barcode"
                value={row.barcode}
                onChange={(e) => updateRow(row.key, { barcode: e.target.value })}
                style={{ width: 120 }}
              />
            ) : null}
            <Input
              type="number"
              step="0.01"
              placeholder="Price"
              value={row.price}
              onChange={(e) => updateRow(row.key, { price: e.target.value })}
              style={{ width: 90 }}
            />
            {row.kind === "product" ? (
              <Input
                type="number"
                placeholder="On hand"
                value={row.qty}
                onChange={(e) => updateRow(row.key, { qty: e.target.value })}
                style={{ width: 90 }}
              />
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeRow(row.key)}
              disabled={rows.length === 1}
              aria-label="Remove row"
            >
              <Icon name="close" size={14} />
            </Button>
          </div>
        ))}
        <Button type="button" variant="secondary" size="sm" onClick={addRow}>
          <Icon name="plus" size={14} /> Add row
        </Button>
      </div>
    </Modal>
  );
}
