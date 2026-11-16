import { formatMoney } from "../../lib/orgSettings";

export interface ReceiptLine {
  description: string;
  quantity: number;
  totalCents: number;
  /** Price of one, the unit it is sold in (kg, crate), and its tax type. */
  unitPriceCents?: number;
  unit?: string;
  taxCode?: string;
  discountBp?: number;
}

/** One row of the VAT analysis: per tax type, the amount before VAT and
 * the VAT. */
export interface ReceiptVat {
  code: string;
  ratePct: number;
  taxableCents: number;
  vatCents: number;
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
  address?: string;
  phone?: string;
  store?: string;
  pricesIncludeVat?: boolean;
  /** A business buying: its KRA PIN goes on the receipt and the eTIMS invoice. */
  buyerPin?: string;
  buyerName?: string;
  /** VAT by tax type, when the sale has more than one. */
  taxLines?: { label: string; cents: number }[];
  vat?: ReceiptVat[];
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
  const html = receiptHtml(r);
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

/** The receipt as a standard till receipt: who sold (name, address,
 * phone, KRA PIN), when and where (date and time, store, till, cashier,
 * receipt number), the buyer's PIN for a business, every item (quantity,
 * unit, price, amount and tax type), the total, the VAT by tax type with
 * the amount before VAT, how it was paid and the change. */
export function receiptHtml(r: Receipt): string {
  const m = (c: number) => esc(formatMoney(c, { currency: r.currency }));
  const qty = (n: number) => String(Math.round(n * 1000) / 1000);
  const rows = r.lines
    .map((l) => {
      const each = l.unitPriceCents != null ? ` × ${m(l.unitPriceCents)}` : " ×";
      const off = l.discountBp ? ` (-${l.discountBp / 100}%)` : "";
      const code = l.taxCode ? ` <b>${esc(l.taxCode)}</b>` : "";
      return `<tr><td>${esc(l.description)}<br><small>${qty(l.quantity)}${l.unit ? ` ${esc(l.unit)}` : ""}${each}${off}</small></td><td class="r">${m(l.totalCents)}${code}</td></tr>`;
    })
    .join("");
  const pays = r.payments
    .map((p) => `<tr><td>${esc(methodLabel(p.method))}</td><td class="r">${m(p.cents)}</td></tr>`)
    .join("");
  const items = r.lines.length;
  const vatTable =
    r.showTax === false || !r.vat?.length
      ? r.showTax === false
        ? ""
        : `<table><tr><td>${esc(r.taxLabel)}</td><td class="r">${m(r.taxCents)}</td></tr></table>`
      : `<table class="vat"><tr><th>Tax</th><th class="r">Before VAT</th><th class="r">VAT</th></tr>${r.vat
          .map(
            (v) =>
              `<tr><td>${esc(v.code)} ${v.ratePct}%</td><td class="r">${m(v.taxableCents)}</td><td class="r">${m(v.vatCents)}</td></tr>`,
          )
          .join("")}<tr><td><b>Total VAT</b></td><td></td><td class="r"><b>${m(r.taxCents)}</b></td></tr></table>`;
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(r.number)}</title>
<style>
  @page { size: 80mm auto; margin: 4mm; }
  body { font: 12px/1.4 ui-monospace, Consolas, monospace; color: #000; margin: 0; }
  h1 { font-size: 15px; text-align: center; margin: 0 0 2px; }
  .c { text-align: center; } .r { text-align: right; white-space: nowrap; }
  table { width: 100%; border-collapse: collapse; } td, th { vertical-align: top; padding: 1px 0; }
  th { font-weight: 400; text-align: left; border-bottom: 1px solid #000; }
  hr { border: 0; border-top: 1px dashed #000; margin: 6px 0; }
  .big td { font-size: 14px; font-weight: 700; }
</style></head><body>
<h1>${esc(r.businessName || "Receipt")}</h1>
${r.address ? `<div class="c">${esc(r.address)}</div>` : ""}
${r.phone ? `<div class="c">Tel ${esc(r.phone)}</div>` : ""}
${r.taxPin ? `<div class="c">PIN ${esc(r.taxPin)}</div>` : ""}
<hr>
<div>Receipt ${esc(r.number)}</div>
<div>${esc(r.at.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "numeric" }))} ${esc(r.at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</div>
<div>${r.store ? `${esc(r.store)} · ` : ""}${esc(r.registerName)} · ${esc(r.cashier)}</div>
${r.buyerPin ? `<div>Buyer PIN ${esc(r.buyerPin)}${r.buyerName ? `<br>${esc(r.buyerName)}` : ""}</div>` : ""}
<hr><table>${rows}</table><hr>
<table>
<tr><td>${items} item${items === 1 ? "" : "s"}</td><td></td></tr>
<tr class="big"><td>Total</td><td class="r">${m(r.totalCents)}</td></tr>
</table>
${r.pricesIncludeVat === false ? "" : r.showTax === false ? "" : `<div><small>Prices include VAT.</small></div>`}
${vatTable}
<hr><table>
${pays}
${r.changeCents > 0 ? `<tr><td>Change</td><td class="r">${m(r.changeCents)}</td></tr>` : ""}
</table><hr><div class="c">${esc(r.footer || "Thank you")}</div>
</body></html>`;
}
