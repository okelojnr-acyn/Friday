use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LineItem {
    pub description: String,
    pub quantity: f64,
    pub unit_price_cents: i64,
    /// Set when this line was rung up from the product catalog (search or
    /// barcode scan) rather than typed freeform -- carried through the
    /// offline queue so Inventory's stock-decrement webhook has something
    /// to key on even for a sale that synced long after checkout (see
    /// apps/inventory/app/main.py's pos-sale subscriber). `#[serde(default)]`
    /// keeps old queued JSON without this field deserializable.
    #[serde(default)]
    pub product_id: Option<String>,
    /// Basis points, e.g. 1000 = 10% off -- set via Cart::set_line_discount_bp,
    /// never through add_line, so editing one line's discount can never
    /// disturb another line's price. Replaces an earlier approach that
    /// baked the discount directly into unit_price_cents client-side,
    /// which lost the original price and couldn't be reported on.
    #[serde(default)]
    pub discount_bp: i64,
    /// The product's cost basis at sale time, when known (rung up from
    /// the catalog) -- None for freeform/ad-hoc lines. Carried through
    /// unchanged to invoicing.pos_sale.recorded / invoicing.invoice.paid
    /// so Accounting's COGS webhook has something to post against,
    /// without Accounting ever querying Inventory directly (apps never
    /// call each other outside the kernel event bus).
    #[serde(default)]
    pub unit_cost_cents: Option<i64>,
}

impl LineItem {
    pub fn total_cents(&self) -> i64 {
        let gross = self.quantity * self.unit_price_cents as f64;
        let discounted = gross * (10_000 - self.discount_bp) as f64 / 10_000.0;
        discounted.round() as i64
    }
}

/// The in-progress sale at the register. Pure domain logic, no I/O -- this
/// is what makes it safe to run identically in the browser (via WASM) and
/// natively (tests, or a future kiosk/offline-device build) without any
/// code duplicated between them.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Cart {
    pub lines: Vec<LineItem>,
    /// basis points, e.g. 800 = 8.00%
    pub tax_rate_bp: i64,
}

impl Cart {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_tax_rate_bp(tax_rate_bp: i64) -> Self {
        Self { lines: Vec::new(), tax_rate_bp }
    }

    pub fn add_line(
        &mut self,
        description: String,
        quantity: f64,
        unit_price_cents: i64,
        product_id: Option<String>,
        unit_cost_cents: Option<i64>,
    ) {
        self.lines.push(LineItem {
            description,
            quantity,
            unit_price_cents,
            product_id,
            discount_bp: 0,
            unit_cost_cents,
        });
    }

    /// The only way a line's discount changes -- clamped to [0, 10000]
    /// (0% to 100% off) so a typo can't produce a negative total_cents.
    /// Returns false if `index` is out of range (mirrors remove_line).
    pub fn set_line_discount_bp(&mut self, index: usize, discount_bp: i64) -> bool {
        match self.lines.get_mut(index) {
            Some(line) => {
                line.discount_bp = discount_bp.clamp(0, 10_000);
                true
            }
            None => false,
        }
    }

    pub fn remove_line(&mut self, index: usize) -> bool {
        if index < self.lines.len() {
            self.lines.remove(index);
            true
        } else {
            false
        }
    }

    pub fn clear(&mut self) {
        self.lines.clear();
    }

    pub fn subtotal_cents(&self) -> i64 {
        self.lines.iter().map(LineItem::total_cents).sum()
    }

    pub fn tax_cents(&self) -> i64 {
        (self.subtotal_cents() as f64 * self.tax_rate_bp as f64 / 10_000.0).round() as i64
    }

    pub fn total_cents(&self) -> i64 {
        self.subtotal_cents() + self.tax_cents()
    }

    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_cart_totals_zero() {
        let cart = Cart::new();
        assert_eq!(cart.subtotal_cents(), 0);
        assert_eq!(cart.tax_cents(), 0);
        assert_eq!(cart.total_cents(), 0);
        assert!(cart.is_empty());
    }

    #[test]
    fn totals_with_tax() {
        let mut cart = Cart::with_tax_rate_bp(800); // 8%
        cart.add_line("Coffee".into(), 2.0, 350, None, None); // 700
        cart.add_line("Pastry".into(), 1.0, 450, None, None); // 450
        assert_eq!(cart.subtotal_cents(), 1150);
        assert_eq!(cart.tax_cents(), 92); // 1150 * 0.08 = 92
        assert_eq!(cart.total_cents(), 1242);
    }

    #[test]
    fn remove_line_by_index() {
        let mut cart = Cart::new();
        cart.add_line("A".into(), 1.0, 100, None, None);
        cart.add_line("B".into(), 1.0, 200, None, None);
        assert!(cart.remove_line(0));
        assert_eq!(cart.lines.len(), 1);
        assert_eq!(cart.lines[0].description, "B");
        assert!(!cart.remove_line(5));
    }

    #[test]
    fn fractional_quantity_rounds_total() {
        let mut cart = Cart::new();
        cart.add_line("Bulk rice (kg)".into(), 1.5, 333, None, None);
        // 1.5 * 333 = 499.5 -> rounds to 500
        assert_eq!(cart.subtotal_cents(), 500);
    }

    #[test]
    fn new_line_has_zero_discount() {
        let mut cart = Cart::new();
        cart.add_line("Widget".into(), 1.0, 1000, None, None);
        assert_eq!(cart.lines[0].discount_bp, 0);
        assert_eq!(cart.lines[0].total_cents(), 1000);
    }

    #[test]
    fn discount_reduces_line_total() {
        let mut cart = Cart::new();
        cart.add_line("Widget".into(), 1.0, 1000, None, None);
        assert!(cart.set_line_discount_bp(0, 1000)); // 10% off
        assert_eq!(cart.lines[0].total_cents(), 900);
        assert_eq!(cart.subtotal_cents(), 900);
    }

    #[test]
    fn discount_and_tax_compose_correctly() {
        // 10% off a $10 line, then 8% tax on the discounted subtotal --
        // matches apps/invoicing/app/main.py's record_pos_sale, which
        // must reconcile against exactly this number.
        let mut cart = Cart::with_tax_rate_bp(800);
        cart.add_line("Widget".into(), 1.0, 1000, None, None);
        cart.set_line_discount_bp(0, 1000);
        assert_eq!(cart.subtotal_cents(), 900);
        assert_eq!(cart.tax_cents(), 72); // 900 * 0.08 = 72
        assert_eq!(cart.total_cents(), 972);
    }

    #[test]
    fn discount_is_clamped_to_100_percent() {
        let mut cart = Cart::new();
        cart.add_line("Widget".into(), 1.0, 1000, None, None);
        cart.set_line_discount_bp(0, 15_000); // 150% -- nonsensical input
        assert_eq!(cart.lines[0].discount_bp, 10_000);
        assert_eq!(cart.lines[0].total_cents(), 0);
    }

    #[test]
    fn set_line_discount_bp_on_missing_index_returns_false() {
        let mut cart = Cart::new();
        assert!(!cart.set_line_discount_bp(0, 1000));
    }

    #[test]
    fn editing_one_lines_discount_does_not_affect_another() {
        let mut cart = Cart::new();
        cart.add_line("A".into(), 1.0, 1000, None, None);
        cart.add_line("B".into(), 1.0, 1000, None, None);
        cart.set_line_discount_bp(0, 5000); // 50% off A only
        assert_eq!(cart.lines[0].total_cents(), 500);
        assert_eq!(cart.lines[1].total_cents(), 1000);
    }

    #[test]
    fn unit_cost_cents_is_carried_through() {
        let mut cart = Cart::new();
        cart.add_line("Widget".into(), 1.0, 1000, Some("prod-1".into()), Some(400));
        assert_eq!(cart.lines[0].unit_cost_cents, Some(400));
    }
}
