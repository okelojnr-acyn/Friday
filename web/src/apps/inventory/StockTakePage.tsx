import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { fetchProductCatalog, type Product } from "../../lib/inventory";
import { localDay } from "../../lib/localTime";
import { formatMoney } from "../../lib/orgSettings";
import { fmtQty } from "../../lib/units";
import { AppHint } from "../../shell/AppFrame";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Field";

const DRAFT_KEY = "friday.stocktake.draft";

/** Typed counts that differ from the record, with the difference at cost.
 * Blank or unreadable counts are skipped, never read as zero. */
export function countDiffs<P extends { id: string; on_hand_qty: number; cost_cents: number }>(products: P[], counted: Record<string, string>) {
  return products.flatMap((p) => {
    const raw = counted[p.id];
    if (raw === undefined || raw.trim() === "") return [];
    const n = Number(raw.trim());
    if (!Number.isFinite(n) || n < 0) return [];
    const delta = n - Number(p.on_hand_qty);
    return delta === 0 ? [] : [{ p, n, delta, value: Math.round(delta * (p.cost_cents || 0)) }];
  });
}

/** Inventory > Stock count (roadmap item 7): count the whole shelf in one
 * go, see what's different and what it's worth, then post it. Each
 * difference is one recorded stock move ("stock take <day>") through the
 * same adjust-stock as the product page, so the books follow at cost.
 * Counts typed so far survive a reload (this browser only) until posted. */
export function StockTakePage() {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [counted, setCounted] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
    } catch {
      return {};
    }
  });
  const [query, setQuery] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [posting, setPosting] = useState(false);
  const [result, setResult] = useState<{ ok: number; failed: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    fetchProductCatalog()
      .then((ps) => setProducts(ps.filter((p) => p.track_inventory).sort((a, b) => a.name.localeCompare(b.name))))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the products"));
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(counted));
    } catch {
      /* private mode: counts live until the page closes */
    }
  }, [counted]);

  const diffs = useMemo(() => countDiffs(products ?? [], counted), [products, counted]);
  const typed = Object.values(counted).filter((v) => v.trim() !== "").length;
  const net = diffs.reduce((t, d) => t + d.value, 0);
  const shown = (products ?? []).filter((p) => !query || `${p.name} ${p.sku} ${p.barcode}`.toLowerCase().includes(query.toLowerCase()));

  async function post() {
    setPosting(true);
    setError(null);
    const failed: string[] = [];
    const failedIds = new Set<string>();
    let ok = 0;
    // shortcut: one request per product; add a bulk endpoint if counts run to thousands.
    for (const d of diffs) {
      try {
        await api.post(`/api/inventory/products/${d.p.id}/adjust-stock`, {
          delta: d.delta,
          reason: "manual_adjustment",
          reference: `stock take ${localDay()}`,
        });
        ok++;
      } catch (err) {
        failed.push(`${d.p.name}: ${err instanceof ApiError ? err.message : "not saved"}`);
        failedIds.add(d.p.id);
      }
    }
    setResult({ ok, failed });
    // Keep only what didn't save, to try again.
    setCounted((cur) => Object.fromEntries(Object.entries(cur).filter(([id]) => failedIds.has(id))));
    setReviewing(false);
    setPosting(false);
    load();
  }

  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">Stock count</h1>
          <AppHint />
        </div>
      </div>
      {error ? (
        <p role="alert" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      ) : null}
      {result ? (
        <p role="status" className="card card-padded" style={{ margin: "0 0 12px" }}>
          Posted {result.ok} change{result.ok === 1 ? "" : "s"}.
          {result.failed.length ? ` Not saved: ${result.failed.join("; ")}. Their counts are kept to try again.` : " Stock and the books now match the count."}
        </p>
      ) : null}

      {reviewing ? (
        <div className="card card-padded" style={{ display: "grid", gap: 10 }}>
          <strong>
            {diffs.length} product{diffs.length === 1 ? "" : "s"} differ from the record
          </strong>
          <table className="table" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Product</th>
                <th style={{ textAlign: "right" }}>Record</th>
                <th style={{ textAlign: "right" }}>Counted</th>
                <th style={{ textAlign: "right" }}>Difference</th>
                <th style={{ textAlign: "right" }}>At cost</th>
              </tr>
            </thead>
            <tbody>
              {diffs.map((d) => (
                <tr key={d.p.id}>
                  <td>{d.p.name}</td>
                  <td style={{ textAlign: "right" }}>{fmtQty(d.p.on_hand_qty)}</td>
                  <td style={{ textAlign: "right" }}>{fmtQty(d.n)}</td>
                  <td style={{ textAlign: "right", color: d.delta < 0 ? "var(--danger)" : undefined }}>
                    {d.delta > 0 ? "+" : ""}
                    {fmtQty(d.delta)}
                  </td>
                  <td style={{ textAlign: "right" }}>{formatMoney(d.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="field-label" style={{ margin: 0 }}>
            {net < 0 ? `Stock worth ${formatMoney(-net)} at cost is missing.` : net > 0 ? `${formatMoney(net)} more stock at cost than the record.` : "The differences cancel out at cost."}
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Button type="button" variant="secondary" onClick={() => setReviewing(false)}>
              Back to counting
            </Button>
            <Button type="button" variant="primary" onClick={() => void post()} disabled={posting}>
              {posting ? "Posting…" : `Post ${diffs.length} change${diffs.length === 1 ? "" : "s"}`}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
            <Input placeholder="Find a product, SKU or barcode…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
            <span className="field-label">
              {typed} counted, {diffs.length} different
            </span>
            <Button type="button" variant="primary" disabled={!diffs.length} onClick={() => setReviewing(true)}>
              Review
            </Button>
          </div>
          {products && products.length === 0 ? <p className="field-label">No products track stock yet.</p> : null}
          <div className="card" style={{ padding: 0 }}>
            <table className="table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Product</th>
                  <th style={{ textAlign: "right" }}>On record</th>
                  <th style={{ width: 140 }}>Counted</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name}
                      {p.sku ? <span className="field-label"> · {p.sku}</span> : null}
                    </td>
                    <td style={{ textAlign: "right" }}>{fmtQty(p.on_hand_qty)}</td>
                    <td>
                      <Input
                        inputMode="decimal"
                        aria-label={`Counted ${p.name}`}
                        placeholder="—"
                        value={counted[p.id] ?? ""}
                        onChange={(e) => setCounted((c) => ({ ...c, [p.id]: e.target.value }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
