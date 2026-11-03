#!/usr/bin/env python3
"""Template for importing a host site's existing products/customers into
a freshly-installed Friday. See INSTALL.md's "Importing existing data"
section for the full procedure this fits into.

This is NOT meant to run from the Friday repo. An installing agent
copies this file into the *host* repo, fills in the two TODO sections
below with that host's actual data access (reading from its database,
CMS API, or a fixture file -- whatever Step 0 of INSTALL.md's research
found), and runs it once against the newly-deployed Friday instance.
Zero dependencies beyond the Python 3 standard library, so it runs
anywhere Python 3 is available, regardless of what the host project's
own stack is.

Usage:
    python host-data-import-template.py --kernel-url https://friday.example.com --token $OWNER_TOKEN
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

# --- TODO (agent fills this in from the host repo's actual data) ---
#
# Each entry mirrors apps/inventory/app/schemas.py's ProductCreate and
# apps/invoicing/app/schemas.py's CustomerCreate -- see those files in
# the Friday repo for the full field list if the host has more detail
# to carry over (sku, barcode, payment_terms_days, etc.).
PRODUCTS: list[dict] = [
    # {"name": "Example Widget", "kind": "product", "price_cents": 1999},
]

CUSTOMERS: list[dict] = [
    # {"name": "Jane Doe", "email": "jane@example.com"},
]
# --- end TODO ---


def post(base_url: str, token: str, path: str, payload: dict) -> dict | list:
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"  FAILED {path}: HTTP {exc.code} -- {body}", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-url", required=True, help="e.g. https://friday.example.com or http://localhost:8080")
    parser.add_argument("--token", required=True, help="a bearer token for an org owner/admin, from Friday's login")
    args = parser.parse_args()
    base = args.kernel_url.rstrip("/")

    if PRODUCTS:
        created = post(base, args.token, "/api/inventory/products/bulk", {"products": PRODUCTS})
        print(f"Imported {len(created)} products.")
    else:
        print("No products to import -- PRODUCTS is empty. Fill it in from the host's data, or skip this step.")

    if CUSTOMERS:
        created = post(base, args.token, "/api/invoicing/customers/bulk", {"customers": CUSTOMERS})
        print(f"Imported {len(created)} customers.")
    else:
        print("No customers to import -- CUSTOMERS is empty. Fill it in from the host's data, or skip this step.")


if __name__ == "__main__":
    main()
