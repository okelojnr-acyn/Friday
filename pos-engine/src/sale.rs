use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::cart::{Cart, LineItem};

/// A completed sale, ready to sync. `client_sale_id` is generated on the
/// device at checkout time and doubles as an idempotency key -- if the
/// same sale gets POSTed to Invoicing twice (flaky connection, retried
/// request), the server treats a repeated id as a no-op rather than a
/// duplicate sale. See apps/invoicing/app/main.py's /pos/sales handler.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Sale {
    pub client_sale_id: String,
    pub lines: Vec<LineItem>,
    pub currency: String,
    pub method: String,
    pub amount_cents: i64,
    pub created_at_ms: i64,
}

impl Sale {
    pub fn from_cart(cart: &Cart, currency: &str, method: &str, now_ms: i64) -> Self {
        Self {
            client_sale_id: Uuid::new_v4().to_string(),
            lines: cart.lines.clone(),
            currency: currency.to_string(),
            method: method.to_string(),
            amount_cents: cart.total_cents(),
            created_at_ms: now_ms,
        }
    }
}

/// Sales that completed at the register but haven't reached Invoicing yet
/// -- the register keeps working with no connection, and flushes this
/// queue once `/api/invoicing/pos/sales` is reachable again.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OfflineQueue {
    pending: Vec<Sale>,
}

impl OfflineQueue {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn enqueue(&mut self, sale: Sale) {
        self.pending.push(sale);
    }

    pub fn pending(&self) -> &[Sale] {
        &self.pending
    }

    pub fn len(&self) -> usize {
        self.pending.len()
    }

    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }

    /// Call once a sale has been confirmed synced by the server.
    pub fn mark_synced(&mut self, client_sale_id: &str) {
        self.pending.retain(|s| s.client_sale_id != client_sale_id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cart::Cart;

    #[test]
    fn enqueue_and_mark_synced() {
        let mut cart = Cart::new();
        cart.add_line("Item".into(), 1.0, 500, None, None);
        let sale = Sale::from_cart(&cart, "USD", "cash", 1_700_000_000_000);

        let mut queue = OfflineQueue::new();
        queue.enqueue(sale.clone());
        assert_eq!(queue.len(), 1);

        queue.mark_synced(&sale.client_sale_id);
        assert!(queue.is_empty());
    }

    #[test]
    fn mark_synced_only_removes_matching_id() {
        let cart = Cart::new();
        let s1 = Sale::from_cart(&cart, "USD", "cash", 1);
        let s2 = Sale::from_cart(&cart, "USD", "card", 2);

        let mut queue = OfflineQueue::new();
        queue.enqueue(s1.clone());
        queue.enqueue(s2.clone());

        queue.mark_synced(&s1.client_sale_id);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.pending()[0].client_sale_id, s2.client_sale_id);
    }
}
