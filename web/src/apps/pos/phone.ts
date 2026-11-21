/** Kenyan mobile numbers at the till: what the cashier types, shown the
 * way people read them, and checked the same way the server checks
 * (apps/invoicing/app/paystack_pay.py kenyan_phone). */

/** The 9 digits after +254 (7xx… or 1xx…), or null while incomplete or wrong. */
export function kePhoneDigits(raw: string): string | null {
  let d = raw.replace(/\D/g, "");
  if (d.startsWith("254")) d = d.slice(3);
  else if (d.startsWith("0")) d = d.slice(1);
  return /^[17]\d{8}$/.test(d) ? d : null;
}

/** "712 345 678" from whatever was typed so far (at most 9 digits). */
export function formatKePhone(raw: string): string {
  let d = raw.replace(/\D/g, "");
  if (d.startsWith("254")) d = d.slice(3);
  else if (d.startsWith("0")) d = d.slice(1);
  d = d.slice(0, 9);
  return [d.slice(0, 3), d.slice(3, 6), d.slice(6)].filter(Boolean).join(" ");
}

/** "+254 712 ••• 678": enough for the customer to recognise, not to copy. */
export function maskKePhone(digits: string): string {
  return `+254 ${digits.slice(0, 3)} ••• ${digits.slice(6)}`;
}

// Self-check, run once in dev: the formats agree with the server's.
if (import.meta.env?.DEV) {
  console.assert(kePhoneDigits("0712 345 678") === "712345678", "07 number");
  console.assert(kePhoneDigits("+254 112-345-678") === "112345678", "+254 01 number");
  console.assert(kePhoneDigits("0812345678") === null, "08 is not mobile");
  console.assert(formatKePhone("0712345") === "712 345", "partial format");
}
