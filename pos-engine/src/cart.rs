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
}

impl LineItem {
    pub fn total_cents(&self) -> i64 {
        (self.quantity * self.unit_price_cents as f64).round() as i64
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

    pub fn add_line(&mut self, description: String, quantity: f64, unit_price_cents: i64, product_id: Option<String>) {
        self.lines.push(LineItem { description, quantity, unit_price_cents, product_id });
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
        cart.add_line("Coffee".into(), 2.0, 350, None); // 700
        cart.add_line("Pastry".into(), 1.0, 450, None); // 450
        assert_eq!(cart.subtotal_cents(), 1150);
        assert_eq!(cart.tax_cents(), 92); // 1150 * 0.08 = 92
        assert_eq!(cart.total_cents(), 1242);
    }

    #[test]
    fn remove_line_by_index() {
        let mut cart = Cart::new();
        cart.add_line("A".into(), 1.0, 100, None);
        cart.add_line("B".into(), 1.0, 200, None);
        assert!(cart.remove_line(0));
        assert_eq!(cart.lines.len(), 1);
        assert_eq!(cart.lines[0].description, "B");
        assert!(!cart.remove_line(5));
    }

    #[test]
    fn fractional_quantity_rounds_total() {
        let mut cart = Cart::new();
        cart.add_line("Bulk rice (kg)".into(), 1.5, 333, None);
        // 1.5 * 333 = 499.5 -> rounds to 500
        assert_eq!(cart.subtotal_cents(), 500);
    }
}
