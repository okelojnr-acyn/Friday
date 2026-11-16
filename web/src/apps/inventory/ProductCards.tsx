import { useMemo, useState } from "react";
import type { Product } from "../../lib/inventory";
import type { RecordRow } from "../../lib/types";
import { formatMoney } from "../../lib/orgSettings";
import { categoryTint, useProductImage } from "../../lib/productImages";
import { fmtQty, unitLabel, useUnits } from "../../lib/units";
import "./inventory.css";

// Low: at or under the reorder point when one is set, else 5.
const LOW = (p: Product) => p.track_inventory && p.on_hand_qty <= (p.reorder_point ? p.reorder_point : 5);

function initials(name: string) {
  return name
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

function Card({ p, variants, categories, onOpen }: { p: Product; variants: Product[]; categories: string[]; onOpen: () => void }) {
  const photo = useProductImage(p);
  const { byId: unitById } = useUnits();
  const unit = unitLabel(unitById.get(p.base_uom_id ?? ""));
  const tint = categoryTint(p.category, categories);
  const priced = variants.length ? variants : [p];
  const from = Math.min(...priced.map((v) => v.price_cents));
  const to = Math.max(...priced.map((v) => v.price_cents));
  const stock = variants.length ? variants.reduce((s, v) => s + (v.track_inventory ? v.on_hand_qty : 0), 0) : p.on_hand_qty;
  const tracked = variants.length ? variants.some((v) => v.track_inventory) : p.track_inventory;
  const low = variants.length ? variants.some(LOW) : LOW(p);
  return (
    <button
      type="button"
      className="inv-card"
      style={{ ["--tile-bar" as string]: tint.bar, ["--tile-soft" as string]: tint.soft }}
      onClick={onOpen}
    >
      <span className="inv-card-photo">
        {photo ? <img src={photo} alt="" loading="lazy" /> : <span className="inv-card-initials">{initials(p.name)}</span>}
      </span>
      <span className="inv-card-body">
        <span className="inv-card-name">{p.name}</span>
        <span className="inv-card-row">
          <span className="inv-card-price">
            {from === to ? formatMoney(from) : `${formatMoney(from)} – ${formatMoney(to)}`}
          </span>
          {tracked ? <span className={`inv-card-stock${low ? " low" : ""}`}>{fmtQty(stock)}{unit && unit !== "pc" ? ` ${unit}` : ""} in stock</span> : <span className="inv-card-stock">Not tracked</span>}
        </span>
        <span className="inv-card-row">
          {p.sku ? <span className="inv-card-sku">{p.sku}</span> : <span />}
          {variants.length ? <span className="inv-chip">{variants.length} variants</span> : null}
        </span>
      </span>
    </button>
  );
}

/** Inventory > Products as cards, grouped by category (owner, 2026-11-16):
 * the photo, price (or price range across variants), stock with low
 * stock in red, and how many variants. Variants show inside their main
 * product's card and editor, not as cards of their own. */
export function ProductCards({ records, onOpen }: { records: RecordRow[]; onOpen: (p: RecordRow) => void }) {
  const products = records as unknown as Product[];
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");

  const variantsOf = useMemo(() => {
    const m = new Map<string, Product[]>();
    for (const p of products) if (p.variant_of) m.set(p.variant_of, [...(m.get(p.variant_of) ?? []), p]);
    return m;
  }, [products]);
  const main = products.filter((p) => !p.variant_of);
  const categories = useMemo(
    () => [...new Set(main.map((p) => p.category?.trim() || "Uncategorised"))].sort((a, b) => (a === "Uncategorised" ? 1 : b === "Uncategorised" ? -1 : a.localeCompare(b))),
    [main],
  );
  const query = q.trim().toLowerCase();
  const matches = (p: Product) =>
    !query ||
    [p.name, p.sku, p.barcode, ...(variantsOf.get(p.id) ?? []).flatMap((v) => [v.name, v.sku, v.barcode, v.variant_name ?? ""])]
      .some((x) => (x ?? "").toLowerCase().includes(query));
  const shown = main.filter((p) => matches(p) && (!category || (p.category?.trim() || "Uncategorised") === category));
  const groups = categories
    .map((c) => ({ c, items: shown.filter((p) => (p.category?.trim() || "Uncategorised") === c) }))
    .filter((g) => g.items.length);

  return (
    <div className="inv-cards">
      <div className="inv-toolbar">
        <input className="inv-search" placeholder="Search name, SKU or barcode…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="inv-cats">
          <button type="button" className={`inv-cat${category === "" ? " active" : ""}`} onClick={() => setCategory("")}>
            All · {main.length}
          </button>
          {categories.map((c) => (
            <button
              key={c}
              type="button"
              className={`inv-cat${category === c ? " active" : ""}`}
              style={{ ["--cat-bar" as string]: categoryTint(c === "Uncategorised" ? "" : c, categories).bar }}
              onClick={() => setCategory(category === c ? "" : c)}
            >
              {c}
            </button>
          ))}
        </div>
      </div>
      {groups.length === 0 ? (
        <div className="empty-state">{main.length ? "Nothing matches that search." : "No products yet. Add one, bulk-add, or import a list."}</div>
      ) : (
        groups.map((g) => (
          <section key={g.c} className="inv-group">
            <h2 className="inv-group-title">
              <span className="inv-group-dot" style={{ background: categoryTint(g.c === "Uncategorised" ? "" : g.c, categories).bar }} />
              {g.c} <span className="inv-group-count">{g.items.length}</span>
            </h2>
            <div className="inv-grid">
              {g.items.map((p) => (
                <Card key={p.id} p={p} variants={variantsOf.get(p.id) ?? []} categories={categories} onOpen={() => onOpen(p as unknown as RecordRow)} />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
