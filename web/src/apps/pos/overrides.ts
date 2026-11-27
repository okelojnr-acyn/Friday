/** Price cuts and big discounts at the till (roadmap item 4, plan 20.5):
 * a cashier may make them, but a team leader's or manager's PIN on the
 * till says yes first, as supermarkets do. Leaders and managers don't
 * need anyone. */

// Business settings > Spending sets it (till_discount_pct); 10% on an
// older kernel.
export const BIG_DISCOUNT_BP = 1000;

const SELF_APPROVING = new Set(["owner", "admin", "branch_manager", "team_leader"]);

type Line = { description: string; product_id: string | null; unit_price_cents: number; discount_bp: number };

/** What on this order needs a manager's OK, in words; empty when nothing does. */
export function overridesNeedingApproval(
  lines: Line[],
  shelfPrice: (productId: string) => number | undefined,
  role: string | undefined,
  limitBp: number = BIG_DISCOUNT_BP,
): string[] {
  if (role && SELF_APPROVING.has(role)) return [];
  const out: string[] = [];
  for (const l of lines) {
    const shelf = l.product_id ? shelfPrice(l.product_id) : undefined;
    if (shelf !== undefined && l.unit_price_cents < shelf) out.push(`${l.description}: price lowered`);
    if (l.discount_bp > 0 && l.discount_bp >= limitBp) out.push(`${l.description}: ${l.discount_bp / 100}% off`);
  }
  return out;
}
