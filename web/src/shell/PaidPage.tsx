import { Card } from "../ui/Card";

/** Where a customer lands after paying a Friday pay link or checkout
 * (Paystack, Pesapal). Public: the payer usually isn't a Friday user. The
 * payment itself is recorded from the provider, not from this page. */
export function PaidPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="page-title" style={{ marginBottom: 8 }}>
          Payment received
        </h1>
        <p style={{ margin: 0 }}>
          Thank you. The business sees your payment as soon as the payment provider confirms it. You can close this page.
        </p>
      </Card>
    </div>
  );
}
