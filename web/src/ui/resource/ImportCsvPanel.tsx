import { useMemo, useRef, useState } from "react";
import type { FieldSpec, RecordRow, ResourceSpec } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { createRecord } from "../../lib/resourceApi";
import { buildCsv, downloadTextFile, parseCsv } from "../../lib/csv";
import { Modal } from "../Modal";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Select, Textarea } from "../Field";
import { initialValues, toWireBody } from "./FormView";

interface ImportCsvPanelProps {
  spec: ResourceSpec;
  app: string;
  onClose: () => void;
  onImported: (records: RecordRow[]) => void;
}

const TRUTHY = new Set(["true", "yes", "y", "1"]);

/** Best-effort date normalization: spreadsheets export dates in every
 * format imaginable ("11/9/2026", "2026-11-09 14:30", ...), but the
 * wire format a date/datetime field needs is whatever
 * toDateInputValue/toDatetimeInputValue produce for a real <input
 * type="date">. new Date(...) parses most common formats; if it can't,
 * the raw cell goes through unchanged and the row's own create error
 * surfaces in the results list below rather than silently dropping it. */
function normalizeDateCell(cell: string, withTime: boolean): string {
  const trimmed = cell.trim();
  if (!trimmed) return "";
  const d = new Date(trimmed);
  if (Number.isNaN(d.getTime())) return trimmed;
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  if (!withTime) return date;
  return `${date}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function cellToValue(field: FieldSpec, cell: string): unknown {
  const trimmed = cell.trim();
  switch (field.type) {
    case "boolean":
      return TRUTHY.has(trimmed.toLowerCase());
    case "date":
      return normalizeDateCell(trimmed, false);
    case "datetime":
      return normalizeDateCell(trimmed, true);
    default:
      return trimmed;
  }
}

/** Generic CSV import for any resource's own New-record endpoint --
 * every resource already has one (createRecord), so this needs no new
 * backend route, just a column-to-field mapping and one create call
 * per row. Replaces "ask an engineer to run
 * scripts/host-data-import-template.py by hand" with something a
 * business admin can do themselves, for any app/resource, not just the
 * two the script happened to hardcode (inventory products, invoicing
 * customers). Partial-success by design: one bad row (a date Excel
 * exported strangely, a required field left blank) shouldn't block
 * every other row -- each row's own create error is reported, not the
 * whole batch aborted. */
export function ImportCsvPanel({ spec, app, onClose, onImported }: ImportCsvPanelProps) {
  const [step, setStep] = useState<"input" | "map" | "result">("input");
  const [rawText, setRawText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [dataRows, setDataRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<string[]>([]); // one field name (or "") per CSV column
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [succeeded, setSucceeded] = useState<RecordRow[]>([]);
  const [failures, setFailures] = useState<{ row: number; error: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const importableFields = useMemo(
    () => spec.fields.filter((f) => f.formVisible && f.name !== "id"),
    [spec],
  );

  function downloadTemplate() {
    downloadTextFile(
      `${spec.name}-template.csv`,
      buildCsv(importableFields.map((f) => f.label), []),
    );
  }

  function onFileChosen(file: File) {
    file.text().then(setRawText).catch(() => setParseError("Could not read that file"));
  }

  function parse() {
    setParseError(null);
    const rows = parseCsv(rawText);
    if (rows.length < 2) {
      setParseError("Need a header row plus at least one data row");
      return;
    }
    const [headerRow, ...rest] = rows;
    const normalized = headerRow.map((h) => h.trim());
    setHeaders(normalized);
    setDataRows(rest);
    // Auto-map by matching the header text against each field's label
    // or name, case-insensitively -- exact only; anything that doesn't
    // match lands on "ignore" and the admin maps it by hand below.
    setMapping(
      normalized.map((h) => {
        const lower = h.toLowerCase();
        const match = importableFields.find(
          (f) => f.label.toLowerCase() === lower || f.name.toLowerCase() === lower,
        );
        return match?.name ?? "";
      }),
    );
    setStep("map");
  }

  const unmappedRequiredFields = useMemo(
    () => importableFields.filter((f) => f.required && !mapping.includes(f.name)),
    [importableFields, mapping],
  );

  async function runImport() {
    setImporting(true);
    setProgress(0);
    const ok: RecordRow[] = [];
    const bad: { row: number; error: string }[] = [];
    for (let i = 0; i < dataRows.length; i++) {
      const row = dataRows[i];
      const values = initialValues(spec);
      mapping.forEach((fieldName, colIdx) => {
        if (!fieldName) return;
        const field = importableFields.find((f) => f.name === fieldName);
        if (!field) return;
        values[fieldName] = cellToValue(field, row[colIdx] ?? "");
      });
      try {
        const created = await createRecord(app, spec.name, toWireBody(spec, values));
        ok.push(created);
      } catch (err) {
        bad.push({ row: i + 2, error: err instanceof ApiError ? err.message : "Could not create this row" });
      }
      setProgress(i + 1);
    }
    setSucceeded(ok);
    setFailures(bad);
    setImporting(false);
    setStep("result");
    if (ok.length > 0) onImported(ok);
  }

  return (
    <Modal title={`Import ${spec.labelPlural} from CSV`} onClose={onClose}>
      {step === "input" ? (
        <div className="form-grid">
          <p className="field-label">
            Paste CSV text, or choose a file exported from Excel/Google Sheets/Numbers. The first row
            must be column headers.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Button type="button" variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()}>
              <Icon name="upload" size={14} /> Choose file...
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={downloadTemplate}>
              Download a template for {spec.labelPlural}
            </Button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFileChosen(file);
            }}
          />
          <Textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            rows={10}
            placeholder={`${importableFields.map((f) => f.label).join(",")}\n...`}
            style={{ fontFamily: "monospace", fontSize: 13 }}
          />
          {parseError ? <div className="error-banner">{parseError}</div> : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="button" variant="primary" onClick={parse} disabled={!rawText.trim()}>
              Next: map columns
            </Button>
          </div>
        </div>
      ) : step === "map" ? (
        <div className="form-grid">
          <p className="field-label">
            {dataRows.length} row{dataRows.length === 1 ? "" : "s"} found. Match each column to a
            field, or leave it ignored.
          </p>
          {unmappedRequiredFields.length > 0 ? (
            <div className="error-banner">
              Required and not mapped yet: {unmappedRequiredFields.map((f) => f.label).join(", ")}. Rows
              will likely fail to import until these are mapped.
            </div>
          ) : null}
          <div className="invoice-lines">
            {headers.map((h, colIdx) => (
              <div className="invoice-line-row" key={colIdx}>
                <span style={{ flex: 1, fontFamily: "monospace", fontSize: 13 }}>{h}</span>
                <Icon name="arrow-up-right" size={14} />
                <Select
                  value={mapping[colIdx] ?? ""}
                  onChange={(e) =>
                    setMapping((cur) => cur.map((v, i) => (i === colIdx ? e.target.value : v)))
                  }
                  style={{ width: 200 }}
                >
                  <option value="">-- ignore this column --</option>
                  {importableFields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.label}
                      {f.required ? " *" : ""}
                    </option>
                  ))}
                </Select>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <Button type="button" variant="ghost" onClick={() => setStep("input")}>
              Back
            </Button>
            <div style={{ display: "flex", gap: 8 }}>
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button type="button" variant="primary" onClick={runImport} disabled={importing}>
                {importing ? `Importing ${progress}/${dataRows.length}...` : `Import ${dataRows.length} rows`}
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="form-grid">
          <p>
            Imported <strong>{succeeded.length}</strong> of {dataRows.length} row
            {dataRows.length === 1 ? "" : "s"}.
          </p>
          {failures.length > 0 ? (
            <div className="error-banner" style={{ maxHeight: 220, overflowY: "auto" }}>
              {failures.map((f, i) => (
                <div key={i}>
                  Row {f.row}: {f.error}
                </div>
              ))}
            </div>
          ) : null}
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button type="button" variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
