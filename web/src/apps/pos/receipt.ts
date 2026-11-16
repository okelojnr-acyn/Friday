import { formatMoney } from "../../lib/orgSettings";

export interface ReceiptLine {
  description: string;
  quantity: number;
  totalCents: number;
}

export interface Receipt {
  businessName: string;
  registerName: string;
  cashier: string;
  number: string;
  at: Date;
  lines: ReceiptLine[];
  totalCents: number;
  taxCents: number;
  taxLabel: string;
  payments: { method: string; cents: number }[];
  changeCents: number;
  currency: string;
  /** From Business settings > Tax. */
  taxPin?: string;
  showTax?: boolean;
  footer?: string;
  /** A business buying: its KRA PIN goes on the receipt and the eTIMS invoice. */
  buyerPin?: string;
  buyerName?: string;
  /** VAT by tax type, when the sale has more than one. */
  taxLines?: { label: string; cents: number }[];
}

const METHOD_LABEL: Record<string, string> = {
  cash: "Cash",
  mpesa: "M-Pesa (till/paybill)",
  card: "Card (PDQ)",
  pesapal: "Pesapal",
  other: "Other",
};

export function methodLabel(m: string): string {
  return METHOD_LABEL[m] ?? m;
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

/** An 80 mm receipt, printed through a hidden frame so the till never
 * leaves the register. With the printer's driver set to open the drawer
 * on print, this is also what opens the drawer (see drawer.ts). */
export function printReceipt(r: Receipt): void {
  const m = (c: number) => esc(formatMoney(c, { currency: r.currency }));
  const rows = r.lines
    .map(
      (l) =>
        `<tr><td>${esc(l.description)}<br><small>${l.quantity} ×</small></td><td class="r">${m(l.totalCents)}</td></tr>`,
    )
    .join("");
  const pays = r.payments
    .map((p) => `<tr><td>${esc(methodLabel(p.method))}</td><td class="r">${m(p.cents)}</td></tr>`)
    .join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(r.number)}</title>
<style>
  @page { size: 80mm auto; margin: 4mm; }
  body { font: 12px/1.4 ui-monospace, Consolas, monospace; color: #000; margin: 0; }
  h1 { font-size: 15px; text-align: center; margin: 0 0 2px; }
  .c { text-align: center; } .r { text-align: right; white-space: nowrap; }
  table { width: 100%; border-collapse: collapse; } td { vertical-align: top; padding: 1px 0; }
  hr { border: 0; border-top: 1px dashed #000; margin: 6px 0; }
  .big td { font-size: 14px; font-weight: 700; }
</style></head><body>
<h1>${esc(r.businessName || "Receipt")}</h1>
<div class="c">${esc(r.registerName)} · ${esc(r.at.toLocaleString())}</div>
${r.taxPin ? `<div class="c">PIN ${esc(r.taxPin)}</div>` : ""}
<div class="c">${esc(r.number)} · ${esc(r.cashier)}</div>
${r.buyerPin ? `<div class="c">Buyer PIN ${esc(r.buyerPin)}${r.buyerName ? ` · ${esc(r.buyerName)}` : ""}</div>` : ""}
<hr><table>${rows}</table><hr>
<table>
<tr class="big"><td>Total</td><td class="r">${m(r.totalCents)}</td></tr>
${
  r.showTax === false
    ? ""
    : r.taxLines && r.taxLines.length > 1
      ? r.taxLines.map((t) => `<tr><td>VAT ${esc(t.label)}</td><td class="r">${m(t.cents)}</td></tr>`).join("")
      : `<tr><td>${esc(r.taxLabel)}</td><td class="r">${m(r.taxCents)}</td></tr>`
}
${pays}
${r.changeCents > 0 ? `<tr><td>Change</td><td class="r">${m(r.changeCents)}</td></tr>` : ""}
</table><hr><div class="c">${esc(r.footer || "Thank you")}</div>
</body></html>`;
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(frame);
  const doc = frame.contentDocument;
  if (!doc) return;
  doc.open();
  doc.write(html);
  doc.close();
  frame.contentWindow?.focus();
  setTimeout(() => {
    frame.contentWindow?.print();
    setTimeout(() => frame.remove(), 2000);
  }, 50);
}
