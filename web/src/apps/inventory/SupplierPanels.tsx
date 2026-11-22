import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { KERNEL_URL } from "../../lib/runtimeConfig";
import { loadSession } from "../../lib/session";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";

/** On a supplier: a link to the supplier page (their purchase orders,
 * plan 12.6). They sign in with a code sent to the supplier's email. */
export function SupplierLinkPanel({ record }: { record: RecordRow }) {
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const email = String(record.email ?? "").trim();

  async function make() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ link: string }>("/orgs/supplier-links", {
        supplier_id: record.id,
        supplier_name: String(record.name ?? ""),
        email,
      });
      setLink(r.link);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "Update Friday to share orders with suppliers." : err instanceof Error ? err.message : "Could not make the link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div className="field-label" style={{ marginBottom: 8 }}>
        Supplier page
      </div>
      {!email ? (
        <p className="field-label">Add the supplier's email first: their sign-in code goes there.</p>
      ) : link ? (
        <>
          <p style={{ marginBottom: 8, wordBreak: "break-all" }}>{link}</p>
          <Button
            onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true)).catch(() => {})}
          >
            {copied ? "Copied" : "Copy link"}
          </Button>
          <p className="field-label" style={{ marginTop: 8 }}>
            Send it to {email}. It works for 90 days; making a new one stops this one.
          </p>
        </>
      ) : (
        <>
          <p className="field-label" style={{ marginBottom: 8 }}>
            The supplier sees their orders, acknowledges them, marks them dispatched and adds their invoice.
          </p>
          <Button onClick={make} disabled={busy}>
            {busy ? "Making…" : "Make a link for this supplier"}
          </Button>
        </>
      )}
      {error ? <div className="error-banner" style={{ marginTop: 8 }}>{error}</div> : null}
    </Card>
  );
}

/** On a purchase order: what the supplier said, and their invoice file. */
export function SupplierStatusPanel({ record }: { record: RecordRow }) {
  const [error, setError] = useState<string | null>(null);
  const status = String(record.supplier_status ?? "");
  const hasFile = Boolean(record.invoice_file_sha);
  if (!status && !hasFile) return null;

  async function openInvoice() {
    setError(null);
    const tab = window.open("", "_blank");
    try {
      const token = loadSession()?.token;
      const res = await fetch(`${KERNEL_URL}/api/inventory/purchase_orders/${record.id}/invoice-file`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(res.statusText);
      const url = URL.createObjectURL(await res.blob());
      if (tab) tab.location.href = url;
      else window.location.href = url;
    } catch {
      tab?.close();
      setError("Could not open the invoice");
    }
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div className="field-label">
        Supplier: {status || "no reply yet"}
        {record.supplier_updated_at ? ` (${new Date(String(record.supplier_updated_at)).toLocaleString()})` : ""}
        {record.supplier_note ? ` · "${String(record.supplier_note)}"` : ""}
      </div>
      {hasFile ? (
        <Button variant="ghost" size="sm" onClick={openInvoice} style={{ marginTop: 8 }}>
          Open their invoice {record.supplier_invoice_no ? String(record.supplier_invoice_no) : ""}
        </Button>
      ) : null}
      {error ? <div className="error-banner" style={{ marginTop: 8 }}>{error}</div> : null}
    </Card>
  );
}
