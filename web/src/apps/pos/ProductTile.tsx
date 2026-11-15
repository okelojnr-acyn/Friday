import type { Product } from "../../lib/inventory";
import { formatMoney } from "../../lib/orgSettings";
import { categoryTint, useProductImage } from "../../lib/productImages";

const LOW_STOCK = 5;

/** A shelf tile (owner's reference, 2026-11-16): the photo fills the tile,
 * the name and price sit in a strip under it, a stripe in the category's
 * colour along the bottom, and a count when it's in the order. Without a
 * photo the name sits on a soft wash of the category colour. A product
 * with variants shows "N options" and its lowest price. */
export function ProductTile({
  product,
  category,
  categories,
  count,
  variants,
  onPick,
}: {
  product: Product;
  category: string;
  categories: string[];
  count: number;
  variants: Product[];
  onPick: () => void;
}) {
  const photo = useProductImage(product);
  const tint = categoryTint(category, categories);
  const priced = variants.length ? variants : [product];
  const from = Math.min(...priced.map((v) => v.price_cents));
  const stock = variants.length
    ? variants.filter((v) => v.track_inventory).reduce((s, v) => s + v.on_hand_qty, 0)
    : product.on_hand_qty;
  const tracked = variants.length ? variants.some((v) => v.track_inventory) : product.track_inventory;
  const low = tracked && stock <= LOW_STOCK;

  return (
    <button
      type="button"
      className={`till-tile${photo ? " has-photo" : ""}`}
      style={{ ["--tile-bar" as string]: tint.bar, ["--tile-soft" as string]: tint.soft }}
      onClick={onPick}
    >
      {photo ? (
        <span className="till-tile-photo">
          <img src={photo} alt="" loading="lazy" draggable={false} />
        </span>
      ) : (
        <span className="till-tile-blank">{product.name}</span>
      )}
      {count ? <span className="till-tile-count">{count}</span> : null}
      {variants.length ? <span className="till-tile-options">{variants.length} options</span> : null}
      <span className="till-tile-strip">
        {photo ? <span className="till-tile-name">{product.name}</span> : null}
        <span className="till-tile-meta">
          <span className="till-tile-price">
            {variants.length ? <span className="till-tile-from">from </span> : null}
            {formatMoney(from)}
          </span>
          {tracked && !variants.length ? (
            <span className={`till-tile-stock${low ? " low" : ""}`}>{stock} left</span>
          ) : null}
        </span>
      </span>
    </button>
  );
}

/** Choosing a variant: one large button per size or colour. */
export function VariantPicker({
  product,
  variants,
  onPick,
  onClose,
}: {
  product: Product;
  variants: Product[];
  onPick: (v: Product) => void;
  onClose: () => void;
}) {
  return (
    <div className="till-sheet-backdrop" onClick={onClose}>
      <div className="till-panel glass till-sheet" onClick={(e) => e.stopPropagation()}>
        <h2>{product.name}</h2>
        <div className="till-variant-grid">
          {variants.map((v) => {
            const low = v.track_inventory && v.on_hand_qty <= LOW_STOCK;
            return (
              <button key={v.id} type="button" className="till-variant glass" onClick={() => onPick(v)}>
                <span className="till-variant-name">{v.variant_name || v.name}</span>
                <span className="till-tile-price">{formatMoney(v.price_cents)}</span>
                {v.track_inventory ? (
                  <span className={`till-tile-stock${low ? " low" : ""}`}>{v.on_hand_qty} left</span>
                ) : null}
              </button>
            );
          })}
        </div>
        <button type="button" className="till-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}
