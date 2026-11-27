"""The demo shop's sample data, put in through Friday's own API (so stock,
books and reports follow exactly as for a real shop). Run by seed.sh in
an app container, where the kernel is http://kernel:8080."""

import json
import urllib.error
import urllib.request

K = "http://kernel:8080"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(K + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path}: {e.code} {e.read().decode()[:500]}") from None


owner = call("POST", "/auth/demo", {"as": "owner"})["token"]


def api(method, path, body=None):
    return call(method, path, body, owner)


# Shelf prices include VAT (the Kenyan default the preset sets).
PRODUCTS = [
    ("Unga wa Ugali 2kg", "Flour & grains", 21000, 17500, 60),
    ("Rice Pishori 1kg", "Flour & grains", 22000, 18000, 45),
    ("Sugar 1kg", "Flour & grains", 18500, 15500, 50),
    ("Cooking Oil 1L", "Cooking", 32000, 26500, 30),
    ("Milk 500ml", "Dairy", 6500, 5200, 80),
    ("Yoghurt 500ml", "Dairy", 13000, 10000, 24),
    ("Bread 400g", "Bakery", 6500, 5200, 40),
    ("Eggs (tray of 30)", "Fresh", 48000, 42000, 12),
    ("Tomatoes 1kg", "Fresh", 12000, 8000, 25),
    ("Bar Soap 800g", "Household", 25000, 20000, 30),
    ("Tissue (10 rolls)", "Household", 52000, 44000, 15),
    ("Soda 500ml", "Drinks", 7000, 5000, 96),
]
made = api(
    "POST",
    "/api/inventory/products/bulk",
    {
        "products": [
            {"name": n, "category": c, "price_cents": p, "cost_cents": cost, "on_hand_qty": q, "reorder_point": max(5, q // 5)}
            for n, c, p, cost, q in PRODUCTS
        ]
    },
)
by_name = {p["name"]: p for p in made}

# A morning at the till.
SALES = [
    [("Unga wa Ugali 2kg", 2), ("Sugar 1kg", 1), ("Milk 500ml", 4)],
    [("Bread 400g", 2), ("Milk 500ml", 2)],
    [("Cooking Oil 1L", 1), ("Rice Pishori 1kg", 2), ("Tomatoes 1kg", 1)],
    [("Soda 500ml", 6)],
    [("Eggs (tray of 30)", 1), ("Bread 400g", 1)],
    [("Bar Soap 800g", 2), ("Tissue (10 rolls)", 1)],
    [("Yoghurt 500ml", 3), ("Soda 500ml", 2)],
]
for i, lines in enumerate(SALES):
    total = sum(by_name[n]["price_cents"] * q for n, q in lines)
    api(
        "POST",
        "/api/invoicing/pos/sales",
        {
            "client_sale_id": f"demo-{i}",
            "currency": "KES",
            "method": "mpesa" if i % 3 == 0 else "cash",
            "amount_cents": total,
            "prices_include_tax": True,
            "lines": [
                {"description": n, "quantity": q, "unit_price_cents": by_name[n]["price_cents"], "product_id": by_name[n]["id"],
                 "unit_cost_cents": by_name[n]["cost_cents"]}
                for n, q in lines
            ],
        },
    )

# Customers who buy on account, and their invoices.
hotel = api("POST", "/api/invoicing/customers", {"name": "Savannah Hotel", "email": "", "company": "Savannah Hotel Ltd", "payment_terms_days": 14})
school = api("POST", "/api/invoicing/customers", {"name": "Hillside School", "payment_terms_days": 30, "credit_limit_cents": 5000000})
for customer, lines in [
    (hotel, [("Eggs (tray of 30)", 10), ("Milk 500ml", 40)]),
    (school, [("Unga wa Ugali 2kg", 20), ("Sugar 1kg", 10)]),
]:
    inv = api(
        "POST",
        "/api/invoicing/invoices",
        {
            "customer_id": customer["id"],
            "currency": "KES",
            "lines": [{"description": n, "quantity": q, "unit_price_cents": by_name[n]["price_cents"], "product_id": by_name[n]["id"]} for n, q in lines],
        },
    )
    api("PATCH", f"/api/invoicing/invoices/{inv['id']}/status", {"status": "sent"})

# Deals in the pipeline.
for contact, company, stage, value in [
    ("Peter Otieno", "Lakeside Restaurant", "qualified", 12000000),
    ("Grace Achieng", "St. Mary's Clinic", "proposition", 4500000),
    ("Samuel Kiprop", "Kiprop Hardware", "new", 2000000),
]:
    api("POST", "/api/crm/opportunities", {"contact_name": contact, "company": company, "stage": stage, "value_cents": value, "currency": "KES"})

print("demo data in:", len(made), "products,", len(SALES), "sales, 2 invoices, 3 deals")
