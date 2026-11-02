import type { ComponentType } from "react";
import type { RecordRow } from "../lib/types";
import { InvoiceCreateModal } from "../apps/invoicing/InvoiceCreateModal";

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
  "invoicing.invoice": InvoiceCreateModal,
};
