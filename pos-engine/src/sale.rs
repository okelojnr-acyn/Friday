use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::cart::{Cart, LineItem};

/// One tender in a split-tender sale -- e.g. part cash, part card. Kept
/// as its own type (not just inlined into Sale) so it round-trips
/// through the offline queue's JSON the same way everything else does;
/// see Sale.payments's own doc comment for why this has to live in the
/// Rust struct rather than being decorated on afterward in JS.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PaymentEntry {
    pub method: String,
    pub amount_cents: i64,
}

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
    /// Set only for a split-tender sale (see PosCart::checkout_json's
    /// payments_json param) -- `method` above stays "split" as a
    /// human-readable summary, and this is what record_pos_sale
    /// actually splits into multiple Payment rows. `skip_serializing_if`
    /// keeps every ordinary single-tender sale's JSON exactly as it was
    /// before this field existed, and `default` means a sale queued by
    /// an older build (before this field existed) still deserializes
    /// here -- both matter because sales sit in localStorage across
    /// app updates, not just across one request.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payments: Option<Vec<PaymentEntry>>,
    /// The register shift the sale was rung up in (set by the till after
    /// checkout_json). Kept through the offline queue, so a sale synced
    /// later still lands in its own shift's drawer count.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shift_id: Option<String>,
    /// Fields the till adds after checkout (buyer's KRA PIN, ...), kept
    /// through the offline queue unread, like LineItem::extra.
    #[serde(flatten, default)]
    pub extra: serde_json::Map<String, serde_json::Value>,
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
            payments: None,
            shift_id: None,
            extra: Default::default(),
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
    fn fields_the_till_adds_survive_the_queue() {
        let mut cart = Cart::new();
        cart.add_line("Sugar".into(), 0.5, 18000, Some("p1".into()), None);
        let sale = Sale::from_cart(&cart, "KES", "cash", 1);
        let mut v: serde_json::Value = serde_json::to_value(&sale).unwrap();
        v["buyer_pin"] = "P051234567X".into();
        v["lines"][0]["tax_code"] = "B".into();
        let mut queue = OfflineQueue::new();
        queue.enqueue(serde_json::from_value(v).unwrap());
        let out = serde_json::to_value(queue.pending()).unwrap();
        assert_eq!(out[0]["buyer_pin"], "P051234567X");
        assert_eq!(out[0]["lines"][0]["tax_code"], "B");
        assert_eq!(out[0]["lines"][0]["quantity"], 0.5);
    }

    #[test]
    fn single_tender_sale_has_no_payments_field_in_json() {
        let cart = Cart::new();
        let sale = Sale::from_cart(&cart, "USD", "cash", 1);
        let json = serde_json::to_string(&sale).unwrap();
        assert!(!json.contains("payments"), "skip_serializing_if should omit an absent payments field");
    }

    #[test]
    fn split_tender_payments_round_trip_through_json() {
        let cart = Cart::new();
        let mut sale = Sale::from_cart(&cart, "USD", "split", 1);
        sale.payments = Some(vec![
            PaymentEntry { method: "cash".into(), amount_cents: 600 },
            PaymentEntry { method: "card".into(), amount_cents: 400 },
        ]);

        let json = serde_json::to_string(&sale).unwrap();
        let restored: Sale = serde_json::from_str(&json).unwrap();
        let payments = restored.payments.expect("payments should survive the round trip");
        assert_eq!(payments.len(), 2);
        assert_eq!(payments[0].method, "cash");
        assert_eq!(payments[0].amount_cents, 600);
        assert_eq!(payments[1].amount_cents, 400);
    }

    #[test]
    fn old_queued_json_without_payments_field_still_deserializes() {
        // Simulates a sale queued by a build before this field existed --
        // #[serde(default)] has to make this still work, not just newly
        // created sales.
        let json = r#"{"client_sale_id":"abc","lines":[],"currency":"USD","method":"cash","amount_cents":100,"created_at_ms":1}"#;
        let sale: Sale = serde_json::from_str(json).unwrap();
        assert!(sale.payments.is_none());
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

#[cfg(test)]
mod shift_id_tests {
    use super::*;

    #[test]
    fn a_queued_sale_keeps_its_shift() {
        let json = r#"{"client_sale_id":"a","lines":[],"currency":"KES","method":"cash","amount_cents":100,"created_at_ms":1,"shift_id":"s-1"}"#;
        let mut q = OfflineQueue::default();
        q.enqueue(serde_json::from_str(json).unwrap());
        let restored: OfflineQueue = serde_json::from_str(&serde_json::to_string(&q).unwrap()).unwrap();
        assert_eq!(restored.pending()[0].shift_id.as_deref(), Some("s-1"));
    }

    #[test]
    fn an_older_sale_without_a_shift_still_reads() {
        let json = r#"{"client_sale_id":"a","lines":[],"currency":"USD","method":"cash","amount_cents":100,"created_at_ms":1}"#;
        let sale: Sale = serde_json::from_str(json).unwrap();
        assert!(sale.shift_id.is_none());
        assert!(!serde_json::to_string(&sale).unwrap().contains("shift_id"));
    }
}
