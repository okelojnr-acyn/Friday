import { useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { loadStripeJs } from "../../lib/stripeJs";
import { Button } from "../../ui/Button";

interface PayWithCardPanelProps {
  invoiceId: string;
  balanceCents: number;
  currency: string;
}

/** The one Stripe-specific piece of UI in the product: everything else
 * about an invoice is the generic schema-driven form (FormView.tsx),
 * but "take a card payment" needs Stripe Elements mounted into real DOM,
 * not a FieldSpec. Rendered by FormView only for invoicing's invoice
 * resource, same targeted-special-case shape as resourceApi.ts's
 * UPDATE_PATH_OVERRIDES -- not a general plugin system for every app. */
export function PayWithCardPanel({ invoiceId, balanceCents, currency }: PayWithCardPanelProps) {
  const [stage, setStage] = useState<"idle" | "starting" | "ready" | "paying" | "paid">("idle");
  const [error, setError] = useState<string | null>(null);
  const cardElRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const stripeRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cardRef = useRef<any>(null);
  const clientSecretRef = useRef<string | null>(null);

  if (balanceCents <= 0) return null;

  async function start() {
    setError(null);
    setStage("starting");
    try {
      const resp = await api.post<{ client_secret: string | null; publishable_key: string }>(
        `/api/invoicing/invoices/${invoiceId}/pay-with-card`,
      );
      if (!resp.client_secret || !resp.publishable_key) {
        setError("Stripe did not return what's needed to confirm payment -- check Settings > Integrations > Stripe");
        setStage("idle");
        return;
      }
      clientSecretRef.current = resp.client_secret;
      const Stripe = await loadStripeJs();
      stripeRef.current = Stripe(resp.publishable_key);
      cardRef.current = stripeRef.current.elements().create("card");
      setStage("ready");
      // The card element mounts into a DOM node that only exists once
      // `stage === "ready"` renders it -- deferring one tick lets that
      // render land first.
      setTimeout(() => cardRef.current?.mount(cardElRef.current), 0);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start card payment");
      setStage("idle");
    }
  }

  async function confirm() {
    if (!stripeRef.current || !clientSecretRef.current) return;
    setStage("paying");
    setError(null);
    const result = await stripeRef.current.confirmCardPayment(clientSecretRef.current, {
      payment_method: { card: cardRef.current },
    });
    if (result.error) {
      setError(result.error.message);
      setStage("ready");
      return;
    }
    setStage("paid");
  }

  return (
    <div className="card card-padded" style={{ marginTop: 12 }}>
      <div className="field-label" style={{ marginBottom: 8 }}>
        Pay with card -- {currency} {(balanceCents / 100).toFixed(2)} due
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {stage === "idle" || stage === "starting" ? (
        <Button type="button" onClick={start} disabled={stage === "starting"}>
          {stage === "starting" ? "Starting..." : "Pay with card"}
        </Button>
      ) : stage === "paid" ? (
        <div className="field-label">Payment submitted -- the invoice updates once Stripe confirms it.</div>
      ) : (
        <>
          <div ref={cardElRef} style={{ padding: "10px 0" }} />
          <Button type="button" onClick={confirm} disabled={stage === "paying"}>
            {stage === "paying" ? "Confirming..." : "Confirm payment"}
          </Button>
        </>
      )}
    </div>
  );
}
