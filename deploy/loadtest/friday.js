// Load test for a busy organisation (Friday Host RELIABILITY-PLAN phase D).
// Runs against deploy/compose.yml through Caddy, like a real customer.
//
//   BASE   https://localhost/kernel   TOKEN  an owner token (kernel token)
//   MULT   traffic multiple (1 = the model below)   DURATION  e.g. "5m"
//
// The model (per MULT): 5 tills x 2 sales/min, 20 staff opening pages,
// 50 shoppers browsing the catalogue. Thresholds are the accepted service
// levels: a till sale p95 under 500 ms, under 1% errors.
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE = __ENV.BASE || "https://localhost/kernel";
const MULT = Number(__ENV.MULT || 1);
const DURATION = __ENV.DURATION || "5m";
const headers = { Authorization: `Bearer ${__ENV.TOKEN}`, "Content-Type": "application/json" };
const salesOk = new Counter("sales_recorded");

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: {
    tills: {
      executor: "constant-arrival-rate",
      rate: Math.max(1, Math.round(10 * MULT)),
      timeUnit: "1m",
      duration: DURATION,
      preAllocatedVUs: Math.ceil(5 * MULT),
      maxVUs: Math.ceil(20 * MULT),
      exec: "till",
    },
    staff: { executor: "constant-vus", vus: Math.ceil(20 * MULT), duration: DURATION, exec: "staff" },
    shoppers: { executor: "constant-vus", vus: Math.ceil(50 * MULT), duration: DURATION, exec: "shopper" },
  },
  thresholds: {
    "http_req_duration{scenario:tills}": ["p(95)<500"],
    "http_req_failed{scenario:tills}": ["rate<0.01"],
    "http_req_duration{scenario:staff}": ["p(95)<1500"],
    "http_req_duration{scenario:shoppers}": ["p(95)<800"],
    http_req_failed: ["rate<0.01"],
  },
};

// 40 products with stock, made once before the run.
export function setup() {
  const products = [];
  for (let i = 0; i < 40; i++) {
    const r = http.post(
      `${BASE}/api/inventory/products`,
      JSON.stringify({ name: `Load item ${i}`, price_cents: 5000 + i * 250, on_hand_qty: 1000000, track_inventory: true }),
      { headers },
    );
    check(r, { "product made": (x) => x.status === 201 });
    if (r.status === 201) products.push({ id: r.json("id"), name: r.json("name"), price: r.json("price_cents") });
  }
  if (products.length === 0) throw new Error("no products: is the token right?");
  return { products };
}

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx".replace(/x/g, () => ((Math.random() * 16) | 0).toString(16));
}

export function till(data) {
  const lines = [];
  for (let i = 0, n = 1 + Math.floor(Math.random() * 5); i < n; i++) {
    const p = data.products[Math.floor(Math.random() * data.products.length)];
    lines.push({ description: p.name, product_id: p.id, quantity: 1 + Math.floor(Math.random() * 3), unit_price_cents: p.price });
  }
  const amount = lines.reduce((t, l) => t + l.quantity * l.unit_price_cents, 0);
  const r = http.post(
    `${BASE}/api/invoicing/pos/sales`,
    JSON.stringify({ client_sale_id: `load:${uuid()}`, currency: "KES", method: "cash", amount_cents: amount, lines }),
    { headers, tags: { name: "sale" } },
  );
  if (check(r, { "sale recorded": (x) => x.status === 201 || x.status === 200 })) salesOk.add(1);
}

const today = () => new Date().toISOString().slice(0, 10);
const staffPages = [
  () => `${BASE}/api/invoicing/invoices`,
  () => `${BASE}/api/inventory/products`,
  () => `${BASE}/api/invoicing/pos/sales?day=${today()}`,
  () => `${BASE}/api/accounting/reports/profit-and-loss?start_date=${today().slice(0, 8)}01&end_date=${today()}`,
  () => `${BASE}/api/inventory/stock_moves`,
  () => `${BASE}/orgs/me/permissions`,
];

export function staff() {
  const url = staffPages[Math.floor(Math.random() * staffPages.length)]();
  const r = http.get(url, { headers, tags: { name: url.split("?")[0].replace(BASE, "") } });
  check(r, { "page ok": (x) => x.status === 200 });
  sleep(5 + Math.random() * 20);
}

export function shopper() {
  const r = http.get(`${BASE}/api/inventory/products`, { headers, tags: { name: "catalogue" } });
  check(r, { "catalogue ok": (x) => x.status === 200 });
  sleep(2 + Math.random() * 6);
}
