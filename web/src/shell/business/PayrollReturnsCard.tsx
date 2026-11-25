import { useEffect, useState } from "react";
import { downloadTextFile, parseCsv } from "../../lib/csv";
import { KERNEL_URL } from "../../lib/runtimeConfig";
import { loadSession } from "../../lib/session";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";

const FILES = [
  ["paye", "KRA: PAYE and Housing Levy", "For the P10 on iTax"],
  ["nssf", "NSSF", "Tier I and II, both shares"],
  ["shif", "SHA: SHIF", "For the SHA employer portal"],
] as const;
type Kind = (typeof FILES)[number][0];

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function fetchCsv(kind: Kind, month: string): Promise<string> {
  const session = loadSession();
  const res = await fetch(`${KERNEL_URL}/api/minions/payroll_runs/returns.csv?kind=${kind}&month=${month}`, {
    headers: session ? { Authorization: `Bearer ${session.token}` } : {},
  });
  if (!res.ok) throw new Error(res.status === 404 ? "Update Friday in Friday Host to get payroll returns." : `Could not load the ${kind.toUpperCase()} file (${res.status})`);
  return res.text();
}

/** The month's payroll returns (HR plan phase 2), from the payslips of the
 * month's payroll runs: one file for KRA (PAYE, Housing Levy), NSSF and
 * SHA, to copy into each one's template, and who's missing a number. */
export function PayrollReturnsCard() {
  const [month, setMonth] = useState(lastMonth());
  const [files, setFiles] = useState<Partial<Record<Kind, string>>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFiles({});
    setError(null);
    for (const [kind] of FILES) {
      fetchCsv(kind, month).then(
        (text) => setFiles((f) => ({ ...f, [kind]: text })),
        (e) => setError(e.message),
      );
    }
  }, [month]);

  const rows = (k: Kind) => (files[k] ? parseCsv(files[k]!).slice(1).filter((r) => r.some(Boolean)) : []);
  const people = rows("paye").length;
  const missing = new Set(
    FILES.flatMap(([k]) => rows(k).filter((r) => r[r.length - 1]).map((r) => `${r[k === "paye" ? 1 : k === "nssf" ? 3 : 2]} (${r[r.length - 1]})`)),
  );

  return (
    <div className="card card-padded form-grid" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 16, margin: 0 }}>Payroll returns</h2>
      <p className="field-label" style={{ margin: 0, maxWidth: "65ch" }}>
        From the month's approved and paid payroll runs. Copy each file into the matching template on iTax, the NSSF portal
        and the SHA portal; check the totals there before you submit.
      </p>
      <FieldWrap label="Month">
        <Input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
      </FieldWrap>
      {error ? <div className="error-banner">{error}</div> : null}
      {!error && files.paye !== undefined && people === 0 ? (
        <p className="field-label">No approved payroll runs end in this month.</p>
      ) : null}
      {missing.size ? (
        <div className="error-banner" role="status">
          Fill these in under People → Pay details before filing: {[...missing].join("; ")}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {FILES.map(([kind, label, hint]) => (
          <Button
            key={kind}
            disabled={!files[kind] || people === 0}
            title={hint}
            onClick={() => files[kind] && downloadTextFile(`${kind}-${month}.csv`, files[kind]!)}
          >
            {label}
          </Button>
        ))}
      </div>
    </div>
  );
}
