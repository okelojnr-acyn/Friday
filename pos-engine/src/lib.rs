//! Cart/pricing/tax/offline-queue logic for the POS register. Pure,
//! deterministic, no I/O -- the same crate compiles natively (for tests
//! and `cargo` tooling) and to WASM (for the register screen in
//! `web/src/apps/pos`), so there is exactly one implementation of "how
//! much does this cart cost" in the whole system.

pub mod cart;
pub mod sale;

#[cfg(target_arch = "wasm32")]
pub mod wasm;

pub use cart::{Cart, LineItem};
pub use sale::{OfflineQueue, Sale};
