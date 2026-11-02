// Loads Stripe.js (https://stripe.com/docs/js) once, on demand -- only
// apps/invoicing's "Pay with card" panel needs it, so it's not a
// dependency of the main bundle. `any` is deliberate: Stripe.js attaches
// itself to `window.Stripe` with its own types; pulling in @stripe/
// stripe-js just for the type declarations isn't worth it for the one
// call site this has.
/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    Stripe?: (publishableKey: string) => any;
  }
}

let loading: Promise<(publishableKey: string) => any> | null = null;

export function loadStripeJs(): Promise<(publishableKey: string) => any> {
  if (window.Stripe) return Promise.resolve(window.Stripe);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://js.stripe.com/v3/";
    script.onload = () => (window.Stripe ? resolve(window.Stripe) : reject(new Error("Stripe.js did not load")));
    script.onerror = () => reject(new Error("Could not load Stripe.js"));
    document.head.appendChild(script);
  });
  return loading;
}
