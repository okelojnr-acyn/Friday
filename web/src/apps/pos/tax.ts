import type { OrgSettings } from "../../lib/orgSettings";

/** VAT at the till, line by line. Each product carries an eTIMS tax type
 * (A exempt, B 16%, C zero-rated, D non-VAT, E 8%); a product without one
 * takes the business's default. With shelf prices that include VAT the
 * VAT is worked out of each line; without, it is added on top. */

export interface TaxableLine {
  quantity: number;
  unit_price_cents: number;
  discount_bp: number;
  product_id: string | null;
}

export interface LineTax {
  code: string;
  rate_bp: number;
  total_cents: number;
  vat_cents: number;
}

export interface TillTotals {
  subtotal: number;
  tax: number;
  total: number;
  lines: LineTax[];
  /** Per tax code: the VAT and its rate, for the receipt. */
  byCode: { code: string; rate_bp: number; vat_cents: number; name: string }[];
}

export function lineTotalCents(line: TaxableLine): number {
  return Math.round((line.quantity * line.unit_price_cents * (10_000 - line.discount_bp)) / 10_000);
}

export function tillTotals(
  lines: TaxableLine[],
  taxCodeOf: (productId: string | null) => string,
  settings: Pick<OrgSettings, "tax" | "tax_rate_bp" | "prices_include_tax">,
): TillTotals {
  const registered = settings.tax ? settings.tax.vat_registered : true;
  const defaultCode = settings.tax?.default_code || "B";
  const rates = new Map((settings.tax?.rates ?? []).map((r) => [r.code, r]));
  const inclusive = settings.prices_include_tax;
  const out: LineTax[] = lines.map((l) => {
    const total = lineTotalCents(l);
    // Not VAT-registered: every sale is non-VAT (D) and charges none.
    const code = registered ? taxCodeOf(l.product_id) || defaultCode : "D";
    const rate = !registered ? 0 : rates.get(code)?.rate_bp ?? (code === defaultCode ? settings.tax_rate_bp : 0);
    const vat = inclusive ? Math.round((total * rate) / (10_000 + rate)) : Math.round((total * rate) / 10_000);
    return { code, rate_bp: rate, total_cents: total, vat_cents: vat };
  });
  const subtotal = out.reduce((s, l) => s + l.total_cents, 0);
  const tax = out.reduce((s, l) => s + l.vat_cents, 0);
  const codes = new Map<string, { code: string; rate_bp: number; vat_cents: number; name: string }>();
  for (const l of out) {
    const c = codes.get(l.code) ?? { code: l.code, rate_bp: l.rate_bp, vat_cents: 0, name: rates.get(l.code)?.name ?? l.code };
    c.vat_cents += l.vat_cents;
    codes.set(l.code, c);
  }
  return {
    subtotal,
    tax,
    total: inclusive ? subtotal : subtotal + tax,
    lines: out,
    byCode: [...codes.values()].sort((a, b) => a.code.localeCompare(b.code)),
  };
}
