import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { detectDelimiter, parseCsv } from "../lib/csv";
import {
  importRows,
  listImportTargets,
  listSourceTables,
  readSourceRows,
  type ImportResult,
  type ImportTarget,
  type SourceTable,
} from "../lib/importApi";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";
import { Icon } from "../ui/Icon";

const BATCH = 200;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_ERRORS_SHOWN = 100;

type SourceKind = "csv" | "database";
type Row = Record<string, unknown>;

/** Lower-case letters and digits only, for matching "Unit Price" to "price". */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

const SYNONYMS: Record<string, string[]> = {
  name: ["name", "title", "productname", "customername", "suppliername", "fullname", "description"],
  price_cents: ["price", "unitprice", "sellingprice", "saleprice", "retailprice"],
  cost_cents: ["cost", "unitcost", "costprice", "buyingprice", "purchaseprice"],
  sku: ["sku", "code", "itemcode", "productcode"],
  barcode: ["barcode", "ean", "upc", "gtin"],
  email: ["email", "emailaddress", "mail"],
  phone: ["phone", "phonenumber", "mobile", "tel", "telephone"],
  company: ["company", "companyname", "business", "organisation", "organization"],
  payment_terms_days: ["paymentterms", "terms", "termsdays"],
  reorder_point: ["reorderpoint", "reorderlevel", "minstock", "minimumstock"],
  track_inventory: ["trackinventory", "trackstock", "stocked"],
};

function guessColumn(field: { name: string; label: string }, columns: string[]): string {
  const wanted = new Set([norm(field.name), norm(field.label), ...(SYNONYMS[field.name] ?? [])]);
  return columns.find((c) => wanted.has(norm(c))) ?? "";
}

function guessIdColumn(columns: string[]): string {
  const prefs = ["id", "code", "sku", "customerid", "productid", "supplierid", "ref", "reference"];
  for (const p of prefs) {
    const hit = columns.find((c) => norm(c) === p);
    if (hit) return hit;
  }
  return "";
}

function cell(v: unknown): unknown {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return v;
}

/** Settings > Import (plan 2.4): bring customers, products and suppliers
 * over from a spreadsheet or an old database. Each row keeps the source's
 * own id, so running the same import again updates what it made instead
 * of adding duplicates, and only the mapped columns are written. */
export function ImportPage() {
  const { session } = useAuth();
  const canImport = session?.role === "owner" || session?.role === "admin";

  const [kind, setKind] = useState<SourceKind>("csv");
  const [error, setError] = useState<string | null>(null);

  // CSV
  const [csvRows, setCsvRows] = useState<Row[] | null>(null);
  const [csvColumns, setCsvColumns] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  // Database
  const [dbUrl, setDbUrl] = useState("");
  const [tables, setTables] = useState<SourceTable[] | null>(null);
  const [tableName, setTableName] = useState("");
  const [dbKey, setDbKey] = useState("");
  const [dbPreview, setDbPreview] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);

  // Target and mapping
  const [targets, setTargets] = useState<ImportTarget[] | null>(null);
  const [targetKey, setTargetKey] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [idColumn, setIdColumn] = useState("");
  const [sourceName, setSourceName] = useState("");

  // Run
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(0);
  const [total, setTotal] = useState(0);
  const [result, setResult] = useState<ImportResult | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    if (canImport) listImportTargets().then(setTargets);
  }, [canImport]);

  const table = tables?.find((t) => t.name === tableName) ?? null;
  const columns = kind === "csv" ? csvColumns : (table?.columns.map((c) => c.name) ?? []);
  const previewRows = kind === "csv" ? (csvRows ?? []).slice(0, 5) : (dbPreview ?? []).slice(0, 5);
  const sourceReady = kind === "csv" ? csvRows !== null : dbPreview !== null;
  const target = targets?.find((t) => `${t.app}.${t.entity}` === targetKey) ?? null;
  const effectiveId = kind === "csv" ? idColumn : dbKey;

  // A new source or target starts the mapping over from best guesses.
  useEffect(() => {
    if (!target) return;
    const next: Record<string, string> = {};
    for (const f of target.fields) next[f.name] = guessColumn(f, columns);
    setMapping(next);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey, columns.join("\u0000")]);

  const missingRequired = useMemo(
    () => (target ? target.fields.filter((f) => f.required && !mapping[f.name]) : []),
    [target, mapping],
  );

  function resetSource() {
    setResult(null);
    setError(null);
  }

  function chooseFile(file: File) {
    resetSource();
    if (file.size > MAX_FILE_BYTES) {
      setError("That file is over 20 MB. Split it into smaller files and import each.");
      return;
    }
    file
      .text()
      .then((text) => {
        const records = parseCsv(text, detectDelimiter(text));
        if (records.length < 2) {
          setError("The file needs a header row and at least one row of data.");
          return;
        }
        const seen = new Map<string, number>();
        const headers = records[0].map((h, i) => {
          let name = h.trim() || `Column ${i + 1}`;
          const n = seen.get(name) ?? 0;
          seen.set(name, n + 1);
          if (n > 0) name = `${name} (${n + 1})`;
          return name;
        });
        const rows = records.slice(1).map((r) => {
          const row: Row = {};
          headers.forEach((h, i) => (row[h] = (r[i] ?? "").trim()));
          return row;
        });
        setCsvColumns(headers);
        setCsvRows(rows);
        setIdColumn(guessIdColumn(headers));
        setSourceName(file.name.replace(/\.[^.]+$/, ""));
      })
      .catch(() => setError("Could not read that file."));
  }

  async function connect() {
    resetSource();
    setBusy(true);
    setTables(null);
    setDbPreview(null);
    try {
      const res = await listSourceTables(dbUrl.trim());
      setTables(res.tables);
      if (res.tables.length === 0) setError("Connected, but that database has no tables this login can read.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect to that database.");
    } finally {
      setBusy(false);
    }
  }

  function pickTable(name: string) {
    setTableName(name);
    setDbPreview(null);
    const t = tables?.find((x) => x.name === name);
    const cols = t?.columns.map((c) => c.name) ?? [];
    setDbKey(guessIdColumn(cols) || cols[0] || "");
    setSourceName(name);
  }

  async function loadPreview() {
    if (!table || !dbKey) return;
    setBusy(true);
    setError(null);
    try {
      const res = await readSourceRows(dbUrl.trim(), table.name, dbKey, null, 5);
      setDbPreview(res.rows.map((r) => r.values));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read that table.");
    } finally {
      setBusy(false);
    }
  }

  function toBatch(rows: Row[], idOf: (r: Row) => string) {
    if (!target) return [];
    return rows
      .map((r) => {
        const values: Record<string, unknown> = {};
        for (const f of target.fields) {
          const col = mapping[f.name];
          if (col) values[f.name] = cell(r[col]);
        }
        return { external_id: idOf(r).trim(), values };
      })
      .filter((r) => r.external_id !== "");
  }

  async function run() {
    if (!target) return;
    cancelled.current = false;
    setRunning(true);
    setError(null);
    setDone(0);
    const sum: ImportResult = { inserted: 0, updated: 0, errors: [] };
    setResult({ ...sum });
    const add = (r: ImportResult) => {
      sum.inserted += r.inserted;
      sum.updated += r.updated;
      sum.errors.push(...r.errors.slice(0, Math.max(0, MAX_ERRORS_SHOWN - sum.errors.length)));
      setResult({ ...sum, errors: [...sum.errors] });
    };
    try {
      if (kind === "csv" && csvRows) {
        setTotal(csvRows.length);
        const noId = csvRows.filter((r) => String(r[idColumn] ?? "").trim() === "").length;
        if (noId > 0) {
          sum.errors.push({ external_id: "(blank)", message: `${noId} rows have no ${idColumn} and were skipped` });
        }
        for (let i = 0; i < csvRows.length && !cancelled.current; i += BATCH) {
          const slice = csvRows.slice(i, i + BATCH);
          add(await importRows(target, sourceName.trim(), toBatch(slice, (r) => String(r[idColumn] ?? ""))));
          setDone(Math.min(i + BATCH, csvRows.length));
        }
      } else if (table) {
        setTotal(table.estimated_rows);
        let after: string | null = null;
        let count = 0;
        do {
          const page: { rows: { key: string; values: Row }[]; next: string | null } = await readSourceRows(
            dbUrl.trim(),
            table.name,
            dbKey,
            after,
            BATCH,
          );
          const keyed = page.rows.map((r) => ({ ...r.values, __key: r.key }));
          add(await importRows(target, sourceName.trim(), toBatch(keyed, (r) => String(r.__key))));
          count += page.rows.length;
          setDone(count);
          after = page.next;
        } while (after && !cancelled.current);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The import stopped. Run it again: rows already imported are updated, not added twice.");
    } finally {
      setRunning(false);
    }
  }

  if (!canImport) {
    return (
      <div className="page">
        <h1 className="page-title">Import</h1>
        <p className="field-label">Only owners and admins can import data.</p>
      </div>
    );
  }

  const canRun =
    !!target && sourceReady && !!effectiveId && missingRequired.length === 0 && sourceName.trim() !== "" && !running;

  return (
    <div className="page" style={{ maxWidth: 920 }}>
      <div className="page-header">
        <h1 className="page-title">Import</h1>
      </div>
      <p className="field-label" style={{ maxWidth: "60ch", marginBottom: 16 }}>
        Bring customers, products and suppliers over from a spreadsheet or your old system&apos;s
        database. Run the same import again any time: rows it already brought in are updated, not
        added twice.
      </p>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      <div className="card card-padded" style={{ marginBottom: 16 }}>
        <div className="field-label" style={{ marginBottom: 8 }}>1. Where the data is</div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <Button
            type="button"
            size="sm"
            variant={kind === "csv" ? "primary" : "secondary"}
            onClick={() => (setKind("csv"), resetSource())}
          >
            <Icon name="upload" size={14} /> Spreadsheet (CSV)
          </Button>
          <Button
            type="button"
            size="sm"
            variant={kind === "database" ? "primary" : "secondary"}
            onClick={() => (setKind("database"), resetSource())}
          >
            <Icon name="database" size={14} /> Old database (PostgreSQL)
          </Button>
        </div>

        {kind === "csv" ? (
          <div className="form-grid">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={() => fileRef.current?.click()}>
                Choose a CSV file
              </Button>
              {csvRows ? (
                <span className="field-label">
                  {csvRows.length} rows, {csvColumns.length} columns
                </span>
              ) : (
                <span className="field-label">Save the sheet as CSV first (File → Download → CSV).</span>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.tsv,.txt,text/csv"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) chooseFile(f);
                e.target.value = "";
              }}
            />
          </div>
        ) : (
          <div className="form-grid">
            <FieldWrap label="Connection URL">
              <div style={{ display: "flex", gap: 8 }}>
                <Input
                  name="import-database-url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="postgres://reader:password@db.example.com:5432/oldshop?sslmode=require"
                  value={dbUrl}
                  onChange={(e) => setDbUrl(e.target.value)}
                  style={{ fontFamily: "var(--font-mono, monospace)", flex: 1 }}
                />
                <Button type="button" onClick={connect} disabled={busy || !dbUrl.trim()}>
                  {busy && !tables ? "Connecting…" : "Connect"}
                </Button>
              </div>
            </FieldWrap>
            <p className="field-label" style={{ maxWidth: "60ch" }}>
              Friday only reads: the connection is read-only and the URL isn&apos;t saved. A login that
              can only SELECT is best.
            </p>
            {tables && tables.length > 0 ? (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                <FieldWrap label="Table">
                  <Select value={tableName} onChange={(e) => pickTable(e.target.value)} style={{ minWidth: 240 }}>
                    <option value="">Choose a table</option>
                    {tables.map((t) => (
                      <option key={t.name} value={t.name}>
                        {t.name} (~{t.estimated_rows.toLocaleString()} rows)
                      </option>
                    ))}
                  </Select>
                </FieldWrap>
                {table ? (
                  <FieldWrap label="Column that identifies each row">
                    <Select value={dbKey} onChange={(e) => (setDbKey(e.target.value), setDbPreview(null))}>
                      {table.columns.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                    </Select>
                  </FieldWrap>
                ) : null}
                {table ? (
                  <Button type="button" variant="secondary" onClick={loadPreview} disabled={busy}>
                    {busy ? "Reading…" : "Read the first rows"}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>

      {sourceReady ? (
        <div className="card card-padded" style={{ marginBottom: 16 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>2. What it becomes in Friday</div>
          {targets === null ? (
            <p className="field-label">Loading…</p>
          ) : targets.length === 0 ? (
            <p className="field-label">Install Invoicing or Inventory first; they hold customers, products and suppliers.</p>
          ) : (
            <div className="form-grid">
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                <FieldWrap label="Import as">
                  <Select value={targetKey} onChange={(e) => setTargetKey(e.target.value)} style={{ minWidth: 200 }}>
                    <option value="">Choose</option>
                    {targets.map((t) => (
                      <option key={`${t.app}.${t.entity}`} value={`${t.app}.${t.entity}`}>
                        {t.label}
                      </option>
                    ))}
                  </Select>
                </FieldWrap>
                {kind === "csv" ? (
                  <FieldWrap label="Column that identifies each row" required>
                    <Select value={idColumn} onChange={(e) => setIdColumn(e.target.value)} style={{ minWidth: 180 }}>
                      <option value="">Choose</option>
                      {columns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </Select>
                  </FieldWrap>
                ) : null}
                <FieldWrap label="Source name">
                  <Input
                    name="import-source-name"
                    autoComplete="off"
                    value={sourceName}
                    onChange={(e) => setSourceName(e.target.value.slice(0, 64))}
                    style={{ width: 200 }}
                  />
                </FieldWrap>
              </div>
              <p className="field-label" style={{ maxWidth: "60ch" }}>
                Use the same source name next time to update these rows. The identifying column must be
                unique per row: an item code, a customer number, or the old system&apos;s id.
              </p>

              {target ? (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Friday field</th>
                      <th>Your column</th>
                      <th>First row</th>
                    </tr>
                  </thead>
                  <tbody>
                    {target.fields.map((f) => (
                      <tr key={f.name}>
                        <td>
                          {f.label}
                          {f.required ? " *" : ""}
                        </td>
                        <td>
                          <Select
                            value={mapping[f.name] ?? ""}
                            onChange={(e) => setMapping({ ...mapping, [f.name]: e.target.value })}
                          >
                            <option value="">Leave as is</option>
                            {columns.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </Select>
                        </td>
                        <td style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 13 }}>
                          {mapping[f.name] && previewRows[0] ? String(cell(previewRows[0][mapping[f.name]])) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
              {target && target.app === "inventory" && target.entity === "product" ? (
                <p className="field-label" style={{ maxWidth: "60ch" }}>
                  Stock levels aren&apos;t imported: count stock in Inventory afterwards, so every unit
                  has a stock move behind it.
                </p>
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      {target && sourceReady ? (
        <div className="card card-padded">
          <div className="field-label" style={{ marginBottom: 8 }}>3. Import</div>
          {missingRequired.length > 0 ? (
            <p className="field-label">Choose a column for {missingRequired.map((f) => f.label).join(", ")}.</p>
          ) : null}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Button type="button" variant="primary" onClick={run} disabled={!canRun}>
              {running ? "Importing…" : `Import ${target.label.toLowerCase()}`}
            </Button>
            {running ? (
              <Button type="button" variant="ghost" onClick={() => (cancelled.current = true)}>
                Stop
              </Button>
            ) : null}
            {running || result ? (
              <span className="field-label">
                {done.toLocaleString()}
                {total ? ` of ${kind === "database" ? "~" : ""}${total.toLocaleString()}` : ""} rows read
              </span>
            ) : null}
          </div>
          {result ? (
            <div style={{ marginTop: 12 }}>
              <p>
                {result.inserted.toLocaleString()} added, {result.updated.toLocaleString()} updated
                {result.errors.length ? `, ${result.errors.length} not imported` : ""}.
              </p>
              {result.errors.length ? (
                <table className="table" style={{ marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((e, i) => (
                      <tr key={i}>
                        <td style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 13 }}>{e.external_id}</td>
                        <td>{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
