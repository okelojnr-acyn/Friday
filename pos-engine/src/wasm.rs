//! WASM bindings consumed by `web/src/apps/pos`. Kept to plain
//! JSON-in/JSON-out methods rather than mapping every Rust type to a JS
//! class -- it's a smaller, more stable surface for the TypeScript side to
//! depend on, and avoids pulling in a serde<->JsValue bridge crate.

use wasm_bindgen::prelude::*;

use crate::cart::Cart;
use crate::sale::{OfflineQueue, PaymentEntry, Sale};

#[wasm_bindgen]
pub struct PosCart {
    inner: Cart,
}

#[wasm_bindgen]
impl PosCart {
    #[wasm_bindgen(constructor)]
    pub fn new(tax_rate_bp: i64) -> PosCart {
        PosCart { inner: Cart::with_tax_rate_bp(tax_rate_bp) }
    }

    pub fn add_line(&mut self, description: String, quantity: f64, unit_price_cents: i64, product_id: Option<String>) {
        self.inner.add_line(description, quantity, unit_price_cents, product_id);
    }

    pub fn remove_line(&mut self, index: usize) -> bool {
        self.inner.remove_line(index)
    }

    pub fn clear(&mut self) {
        self.inner.clear();
    }

    pub fn subtotal_cents(&self) -> i64 {
        self.inner.subtotal_cents()
    }

    pub fn tax_cents(&self) -> i64 {
        self.inner.tax_cents()
    }

    pub fn total_cents(&self) -> i64 {
        self.inner.total_cents()
    }

    pub fn lines_json(&self) -> String {
        serde_json::to_string(&self.inner.lines).unwrap_or_else(|_| "[]".into())
    }

    /// Finalize the cart into a Sale ready to sync, as a JSON string the
    /// JS side hands to `PosOfflineQueue::enqueue_json`. `payments_json`
    /// is an optional JSON array of `{method, amount_cents}` for a
    /// split-tender sale (e.g. part cash, part card) -- omit it (JS:
    /// `undefined`) for the ordinary single-tender case, where `method`
    /// alone describes the whole sale same as always.
    pub fn checkout_json(
        &self,
        currency: &str,
        method: &str,
        now_ms: f64,
        payments_json: Option<String>,
    ) -> Result<String, JsError> {
        let mut sale = Sale::from_cart(&self.inner, currency, method, now_ms as i64);
        if let Some(json) = payments_json {
            let payments: Vec<PaymentEntry> =
                serde_json::from_str(&json).map_err(|e| JsError::new(&e.to_string()))?;
            sale.payments = Some(payments);
        }
        Ok(serde_json::to_string(&sale).unwrap_or_else(|_| "null".into()))
    }
}

#[wasm_bindgen]
pub struct PosOfflineQueue {
    inner: OfflineQueue,
}

#[wasm_bindgen]
impl PosOfflineQueue {
    #[wasm_bindgen(constructor)]
    pub fn new() -> PosOfflineQueue {
        PosOfflineQueue { inner: OfflineQueue::new() }
    }

    pub fn enqueue_json(&mut self, sale_json: &str) -> Result<(), JsError> {
        let sale: Sale = serde_json::from_str(sale_json).map_err(|e| JsError::new(&e.to_string()))?;
        self.inner.enqueue(sale);
        Ok(())
    }

    pub fn pending_json(&self) -> String {
        serde_json::to_string(self.inner.pending()).unwrap_or_else(|_| "[]".into())
    }

    pub fn len(&self) -> usize {
        self.inner.len()
    }

    pub fn mark_synced(&mut self, client_sale_id: &str) {
        self.inner.mark_synced(client_sale_id);
    }

    /// Persist the whole queue (e.g. to IndexedDB) between sessions.
    pub fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_else(|_| "{\"pending\":[]}".into())
    }

    pub fn restore_json(json: &str) -> PosOfflineQueue {
        let inner: OfflineQueue = serde_json::from_str(json).unwrap_or_default();
        PosOfflineQueue { inner }
    }
}
