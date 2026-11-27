import type { ComponentType } from "react";
import type { RecordRow } from "../lib/types";
import { GoToInvoiceEditor, GoToQuoteEditor } from "../apps/invoicing/InvoiceEditorPage";
import { PurchaseOrderCreateModal } from "../apps/inventory/PurchaseOrderCreateModal";

export interface CustomCreateProps {
  onClose: () => void;
  onSaved: (record: RecordRow) => void;
}

/** Same idea as resourceApi.ts's UPDATE_PATH_OVERRIDES: most resources'
 * "New" button can stay the generic FormView, but a handful of create
 * flows need more than a flat field list (an invoice needs a customer
 * and line items, not just its own columns) and get a hand-built screen
 * instead -- keyed by "app.resource" so ResourcePage can look one up
 * without every app needing to know about this mechanism. */
export const CUSTOM_CREATE_SCREENS: Record<string, ComponentType<CustomCreateProps>> = {
  // Invoices get the full editor with a live preview (plan 18.4 step 4).
  "invoicing.invoice": GoToInvoiceEditor,
  // Quotes get the same editor (roadmap item 6).
  "invoicing.quote": GoToQuoteEditor,
  "inventory.purchase_order": PurchaseOrderCreateModal,
};
