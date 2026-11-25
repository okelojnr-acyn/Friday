import { localDay } from "../lib/localTime";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { KERNEL_URL } from "../lib/runtimeConfig";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Badge } from "../ui/Badge";

/** The supplier page (plan 12.6): a supplier opens the link the business
 * sent, gets a code at the email on the link, and sees only their own
 * purchase orders: acknowledge, mark dispatched, add their invoice. No
 * Friday account; the session lasts 12 hours and stays in this tab. */

interface Line {
  id: string;
  description: string;
  quantity: string | number;
  uom_name?: string;
  unit_cost_cents: number;
  total_cost_cents: number;
}
interface Po {
  id: string;
  number: string;
  status: string;
  created_at: string;
  lines: Line[];
  total_due_cents: number;
  supplier_status: string;
  supplier_note: string;
  supplier_invoice_no: string;
  supplier_invoice_date: string | null;
  invoice_file_sha: string;
  paid_at: string | null;
}

const KEY = "friday.supplier";
const money = (cents: number) => (cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${KERNEL_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body.error ?? body.detail ?? res.statusText), { status: res.status });
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export function SupplierPage() {
  const [params] = useSearchParams();
  const t = params.get("t") ?? "";
  const [token, setToken] = useState<string | null>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
      return saved && saved.t === t && saved.until > Date.now() ? saved.token : null;
    } catch {
      return null;
    }
  });
  const [who, setWho] = useState<{ business: string; supplier: string } | null>(null);
  const [hint, setHint] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [orders, setOrders] = useState<Po[] | null>(null);

  const signOut = () => {
    sessionStorage.removeItem(KEY);
    setToken(null);
    setOrders(null);
  };

  useEffect(() => {
    if (!token) return;
    call<Po[]>("/api/inventory/supplier/purchase_orders", {}, token)
      .then(setOrders)
      .catch((e) => {
        if (e.status === 401) signOut();
        else setError(e.message);
      });
  }, [token]);

  async function sendCode() {
    setBusy(true);
    setError("");
    try {
      const r = await call<{ email_hint: string; business: string; supplier: string }>("/supplier/code", {
        method: "POST",
        body: JSON.stringify({ t }),
      });
      setHint(r.email_hint);
      setWho({ business: r.business, supplier: r.supplier });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the code");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await call<{ token: string; expires_in: number; business: string; supplier: string }>("/supplier/verify", {
        method: "POST",
        body: JSON.stringify({ t, code: code.trim() }),
      });
      sessionStorage.setItem(KEY, JSON.stringify({ t, token: r.token, until: Date.now() + r.expires_in * 1000 }));
      setWho({ business: r.business, supplier: r.supplier });
      setToken(r.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That code didn't work");
    } finally {
      setBusy(false);
    }
  }

  const replace = (po: Po) => setOrders((cur) => (cur ?? []).map((p) => (p.id === po.id ? po : p)));

  if (!t) {
    return <Centered>This link is incomplete. Open the full link the business sent you.</Centered>;
  }

  if (!token) {
    return (
      <Centered>
        <h1 className="page-title" style={{ marginBottom: 8 }}>
          Purchase orders
        </h1>
        {!hint ? (
          <>
            <p style={{ marginBottom: 16 }}>We'll email a code to the address the business has for you.</p>
            <Button variant="primary" onClick={sendCode} disabled={busy} style={{ width: "100%" }}>
              {busy ? "Sending…" : "Email me a code"}
            </Button>
          </>
        ) : (
          <form onSubmit={verify}>
            <p style={{ marginBottom: 12 }}>
              {who?.business ? `${who.business} sent ` : "We sent "}a code to {hint}.
            </p>
            <FieldWrap label="Code" required>
              <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" autoFocus />
            </FieldWrap>
            <Button variant="primary" type="submit" disabled={busy || code.trim().length < 6} style={{ width: "100%", marginTop: 12 }}>
              {busy ? "Checking…" : "Open my orders"}
            </Button>
          </form>
        )}
        {error ? (
          <p role="alert" className="text-sm text-destructive" style={{ marginTop: 12 }}>
            {error}
          </p>
        ) : null}
      </Centered>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <h1 className="page-title">{who?.business ? `Orders from ${who.business}` : "Your purchase orders"}</h1>
        <Button variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </div>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      {orders === null ? (
        <div className="page spinner">Loading…</div>
      ) : orders.length === 0 ? (
        <div className="empty-state">No orders for you yet.</div>
      ) : (
        orders.map((po) => <OrderCard key={po.id} po={po} token={token} onChanged={replace} onError={setError} />)
      )}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">{children}</Card>
    </div>
  );
}

function OrderCard({
  po,
  token,
  onChanged,
  onError,
}: {
  po: Po;
  token: string;
  onChanged: (po: Po) => void;
  onError: (m: string) => void;
}) {
  const [note, setNote] = useState(po.supplier_note);
  const [invNo, setInvNo] = useState(po.supplier_invoice_no);
  const [invDate, setInvDate] = useState(po.supplier_invoice_date ?? localDay());
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const received = po.status === "received";

  const run = async (fn: () => Promise<Po>) => {
    setBusy(true);
    onError("");
    try {
      onChanged(await fn());
    } catch (e) {
      onError(e instanceof Error ? e.message : "That didn't work; try again");
    } finally {
      setBusy(false);
    }
  };
  const setStatus = (status: "acknowledged" | "dispatched") =>
    run(() =>
      call<Po>(`/api/inventory/supplier/purchase_orders/${po.id}/status`, { method: "POST", body: JSON.stringify({ status, note }) }, token),
    );
  const sendInvoice = () =>
    file &&
    run(() =>
      call<Po>(
        `/api/inventory/supplier/purchase_orders/${po.id}/invoice?number=${encodeURIComponent(invNo.trim())}&invoice_date=${invDate}`,
        { method: "PUT", body: file, headers: { "Content-Type": file.type || "application/pdf" } },
        token,
      ),
    );

  return (
    <Card style={{ marginBottom: 12 }}>
      <div className="pos-totals-row" style={{ marginBottom: 8 }}>
        <strong>{po.number}</strong>
        <span style={{ display: "flex", gap: 6 }}>
          {received ? <Badge tone="success">received</Badge> : null}
          {po.supplier_status ? <Badge tone="accent">{po.supplier_status}</Badge> : <Badge tone="neutral">new</Badge>}
          {po.paid_at ? <Badge tone="success">paid</Badge> : null}
        </span>
      </div>
      <table className="table" style={{ width: "100%", marginBottom: 8 }}>
        <tbody>
          {po.lines.map((l) => (
            <tr key={l.id}>
              <td>{l.description}</td>
              <td style={{ textAlign: "right" }}>
                {Number(l.quantity)} {l.uom_name ?? ""}
              </td>
              <td style={{ textAlign: "right" }}>{money(l.total_cost_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="pos-totals-row" style={{ marginBottom: 12 }}>
        <span>Total due</span>
        <strong>{money(po.total_due_cents)}</strong>
      </div>
      {!received ? (
        <>
          <FieldWrap label="Note to the business">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. on the 2pm truck" />
          </FieldWrap>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0 12px" }}>
            {po.supplier_status === "" ? (
              <Button onClick={() => setStatus("acknowledged")} disabled={busy}>
                Acknowledge
              </Button>
            ) : null}
            {po.supplier_status !== "dispatched" ? (
              <Button variant="primary" onClick={() => setStatus("dispatched")} disabled={busy}>
                Mark dispatched
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
      {!po.paid_at ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <FieldWrap label="Invoice number" required>
            <Input value={invNo} onChange={(e) => setInvNo(e.target.value)} style={{ width: 150 }} />
          </FieldWrap>
          <FieldWrap label="Invoice date" required>
            <Input type="date" value={invDate} onChange={(e) => setInvDate(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Invoice (PDF or photo)" required>
            <Input type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </FieldWrap>
          <Button onClick={sendInvoice} disabled={busy || !file || !invNo.trim()}>
            {po.invoice_file_sha ? "Replace invoice" : "Add invoice"}
          </Button>
        </div>
      ) : null}
      {po.invoice_file_sha ? (
        <p className="field-label" style={{ marginTop: 8 }}>
          Invoice {po.supplier_invoice_no} added.
        </p>
      ) : null}
    </Card>
  );
}
