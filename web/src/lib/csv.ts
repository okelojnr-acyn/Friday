// Minimal RFC4180-ish CSV read/write -- zero dependencies, same "stdlib
// only" philosophy as scripts/host-data-import-template.py. Handles
// quoted fields (embedded commas/newlines/escaped "" ), \r\n or \n line
// endings. Not a full spec implementation (no BOM handling, no custom
// delimiters) -- it only needs to round-trip what Excel/Sheets/Numbers
// actually export, which this covers.

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  const n = text.length;

  while (i < n) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      i++;
      continue;
    }
    if (c === ",") {
      row.push(field);
      field = "";
      i++;
      continue;
    }
    if (c === "\r") {
      i++;
      continue;
    }
    if (c === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      i++;
      continue;
    }
    field += c;
    i++;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  // Drop fully-blank trailing/stray lines (a trailing newline parses as
  // one extra all-empty row).
  return rows.filter((r) => r.some((cell) => cell.trim() !== ""));
}

function toCsvCell(value: string): string {
  if (/[",\n]/.test(value)) return '"' + value.replace(/"/g, '""') + '"';
  return value;
}

export function buildCsv(headers: string[], rows: string[][]): string {
  const lines = [headers.map(toCsvCell).join(",")];
  for (const r of rows) lines.push(r.map(toCsvCell).join(","));
  return lines.join("\n");
}

/** Triggers a browser download of `content` as `filename` -- a plain
 * Blob + temporary <a download> click, the standard client-side-only
 * way to do this with no server round trip. */
export function downloadTextFile(filename: string, content: string, mimeType = "text/csv"): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
