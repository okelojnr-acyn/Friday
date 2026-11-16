# KRA eTIMS in Friday

eTIMS is KRA's electronic tax invoice system. Every sale a business
makes is meant to be reported there. When a buyer is a business, the
eTIMS invoice carries the buyer's KRA PIN.

Source for everything below: KRA's *OSCU Specification Document v2.0*
(kra.go.ke). The code is in `packages/py-common/friday_common/etims/`.

## What happens when a business buys

1. At the till, the cashier taps **Business customer? Add KRA PIN** on
   the payment screen. The cashier types the PIN (A or P, nine digits, a
   letter) and the business name. The format is checked on the spot.
   With automation on, KRA confirms whose PIN it is (`/selectCustomer`).
2. The receipt prints the buyer's PIN, and the sale is stored with it.
3. The sale must then reach eTIMS as an invoice naming that PIN:
   - **Today (by hand):** Friday → *eTIMS filing* lists the sales that
     need filing. Each one is laid out the way the eTIMS portal asks:
     items, quantity and unit, tax type A–E, VAT. Someone enters it in
     the eTIMS portal or app, then types the invoice number eTIMS gives
     back into Friday. The sale then shows as *Filed*.
   - **Later (automated):** Friday sends the sale to KRA
     (`/saveTrnsSalesOsdc`). KRA answers with the receipt numbers, the
     internal data and a signature. Friday stores them and links the
     receipt to KRA's checker.
4. Once the invoice is in eTIMS:
   - it appears in the buyer's iTax records, so the buyer can claim the
     input VAT and deduct the expense. Expenses without an eTIMS invoice
     are disallowed;
   - the seller's VAT return is pre-filled from eTIMS.
   *eTIMS filing → Download VAT sales (CSV)* gives the business its own
   copy, in the columns of the VAT3 sales schedule, to check against.
5. A return at the till becomes a credit note. In eTIMS it refers to the
   original invoice (`rcptTyCd` R, `orgInvcNo`), so the original sale is
   filed first.

A customer who comes back later for an invoice with their PIN can have
it added in *eTIMS filing*, as long as the sale isn't filed yet. Once a
sale is filed, changing the buyer means a credit note and a new
invoice.

## Tax types

Each product has a tax type (Inventory → product → *Tax type*). A
product without one uses the business default (Business settings →
Tax).

| Code | Meaning     | Rate |
|------|-------------|------|
| A    | Exempt      | 0%   |
| B    | Standard    | 16%  |
| C    | Zero-rated  | 0%   |
| D    | Non-VAT     | 0%   |
| E    | Reduced     | 8%   |

A business that isn't VAT-registered sells everything as D and charges
no VAT.

## Automated sending: built, switched off

- **Shared library** (`friday_common/etims`):
  - the OSCU client: `selectInitOsdcInfo`, `selectCustomer`,
    `selectCodeList`, `saveItem`, `saveTrnsSalesOsdc`;
  - the PIN, branch and CMC key go in the headers;
  - result codes are handled (`000` ok, `001` no result, others raise);
  - payload builders, tested against the specification's own sample.
- **Invoicing:**
  - `POST /etims/send` sends unfiled sales oldest first, credit notes
    after their sale;
  - one `invcNo` sequence per organisation;
  - a refused sale is kept as *KRA refused* with KRA's message and
    retried on the next run.
- **Inventory:** `POST /products/{id}/etims/register` registers a product
  (`/saveItem`). The item code follows the specification:
  `KE` + product type + packaging + unit + 7-digit sequence.
- **Kernel:** `GET /internal/etims/{org}` hands the config, CMC key
  included, to Friday's apps only.

Everything automated is refused unless the server sets
`ETIMS_AUTOMATION=1`.

### Production checks before turning it on

1. KRA approves the OSCU (or VSCU) application. Then run device
   initialisation on the **sandbox** and store the CMC key in Business
   settings → eTIMS.
2. On the sandbox:
   - register a few real products, then send a cash sale, an M-Pesa
     sale, a sale with a buyer PIN, a discounted line, a mixed A/B/E
     sale and a return;
   - compare each reply and the portal's view with Friday's.
3. Confirm the receipt QR/check link format
   (`friday_common/etims/codes.py`, `RECEIPT_CHECK`) against a sandbox
   receipt.
4. Decide when sending runs:
   - after each sale, plus a sweep every few minutes for failed ones;
   - a scheduler that calls `send_unfiled` per org.
5. Item classification codes: pull KRA's list (`/selectItemClsList`)
   so products pick a valid code rather than typing one.
6. Set `ETIMS_AUTOMATION=1` on one customer's own server first.
7. Optional: GavaConnect's PIN checker (developer.go.ke) for PIN lookup
   without an eTIMS device.
