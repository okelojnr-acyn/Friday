import { useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { Product } from "../../lib/inventory";
import { PACKAGING_UNITS } from "../../lib/etims";
import { fixedFactor, fmtQty, unitLabel, useUnits, type Unit } from "../../lib/units";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import { removeProductImage, uploadProductImage, useProductImage } from "../../lib/productImages";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { Checkbox, FieldWrap, Input, Select } from "../../ui/Field";
import { Modal } from "../../ui/Modal";
import "./inventory.css";

const toCents = (s: string) => Math.round((Number.parseFloat(s || "0") || 0) * 100);
const toAmount = (c: number) => (c ? (c / 100).toFixed(2) : "");

/** One product: photo, details, and its variants (owner, 2026-11-16). A
 * variant is a full product (own price, SKU, barcode, stock) that names
 * this one; the till shows one tile and asks which. */
export function ProductEditor({
  product,
  all,
  onClose,
  onSaved,
}: {
  product?: Product;
  all: Product[];
  onClose: () => void;
  onSaved: (changed: RecordRow[]) => void;
}) {
  const isNew = !product;
  const [name, setName] = useState(product?.name ?? "");
  const [category, setCategory] = useState(product?.category ?? "");
  const [price, setPrice] = useState(toAmount(product?.price_cents ?? 0));
  const [cost, setCost] = useState(toAmount(product?.cost_cents ?? 0));
  const [sku, setSku] = useState(product?.sku ?? "");
  const [barcode, setBarcode] = useState(product?.barcode ?? "");
  const [track, setTrack] = useState(product?.track_inventory ?? true);
  const [online, setOnline] = useState(product?.sell_online ?? true);
  const [taxCode, setTaxCode] = useState(product?.tax_code ?? "");
  const [itemClass, setItemClass] = useState(product?.etims_item_class ?? "");
  const [pkgUnit, setPkgUnit] = useState(product?.etims_packaging_unit || "NT");
  const settings = useOrgSettings();
  const rates = settings.tax?.rates ?? [];
  const defaultRate = rates.find((r) => r.code === (settings.tax?.default_code || "B"));
  const [startStock, setStartStock] = useState("");
  // Units: stock in the base unit; bought and sold in their own units.
  const { units, byId: unitById } = useUnits();
  const piece = units.find((u) => u.code === "pc");
  const [baseId, setBaseId] = useState(product?.base_uom_id ?? "");
  const [purchaseId, setPurchaseId] = useState(product?.purchase_uom_id ?? "");
  const [salesId, setSalesId] = useState(product?.sales_uom_id ?? "");
  const [purchaseFactor, setPurchaseFactor] = useState(product?.purchase_factor ? String(product.purchase_factor) : "");
  const [salesFactor, setSalesFactor] = useState(product?.sales_factor ? String(product.sales_factor) : "");
  const base = unitById.get(baseId) ?? piece;
  const purchaseUnit = unitById.get(purchaseId) ?? base;
  const salesUnit = unitById.get(salesId) ?? base;
  const baseLabel = unitLabel(base) || "units";
  const [sha, setSha] = useState(product?.image_sha ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const photo = useProductImage({ id: product?.id ?? "new", image_sha: sha });

  const categories = useMemo(
    () => [...new Set(all.map((p) => p.category?.trim()).filter((c): c is string => !!c))].sort(),
    [all],
  );
  const [variants, setVariants] = useState<Product[]>(() =>
    product ? all.filter((p) => p.variant_of === product.id).sort((a, b) => a.price_cents - b.price_cents) : [],
  );
  const [nv, setNv] = useState({ name: "", price: "", sku: "", barcode: "", stock: "" });
  // A new product's variants wait here and are created right after it.
  const [pending, setPending] = useState<typeof nv[]>([]);
  const isVariant = !!product?.variant_of;

  function pickFile(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  async function save() {
    if (!name.trim()) {
      setError("Give the product a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        category: category.trim(),
        price_cents: toCents(price),
        cost_cents: toCents(cost),
        sku: sku.trim(),
        barcode: barcode.trim(),
        track_inventory: track,
        sell_online: online,
        ...unitFields(),
        tax_code: taxCode,
        etims_item_class: itemClass.trim(),
        etims_packaging_unit: pkgUnit,
      };
      let saved = isNew
        ? await api.post<Product>("/api/inventory/products", { ...body, on_hand_qty: Number.parseFloat(startStock || "0") || 0 })
        : await api.patch<Product>(`/api/inventory/products/${product!.id}`, body);
      if (file) {
        const newSha = await uploadProductImage(saved.id, file);
        saved = { ...saved, image_sha: newSha };
      }
      const made: Product[] = [];
      for (const v of pending) {
        made.push(await api.post<Product>("/api/inventory/products", variantBody(saved, v)));
      }
      onSaved([saved, ...made] as unknown as RecordRow[]);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function dropPhoto() {
    if (!product) {
      setFile(null);
      setPreview(null);
      return;
    }
    setBusy(true);
    try {
      await removeProductImage(product.id);
      setSha("");
      setFile(null);
      setPreview(null);
      onSaved([{ ...product, image_sha: "" } as unknown as RecordRow]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the photo.");
    } finally {
      setBusy(false);
    }
  }

  /** The unit fields to save; none until the units have loaded. */
  function unitFields(): Record<string, unknown> {
    if (!base) return {};
    const out: Record<string, unknown> = {
      base_uom_id: base.id,
      purchase_uom_id: purchaseUnit?.id ?? base.id,
      sales_uom_id: salesUnit?.id ?? base.id,
    };
    if (fixedFactor(base, purchaseUnit) == null) out.purchase_factor = Number.parseFloat(purchaseFactor) || undefined;
    if (fixedFactor(base, salesUnit) == null) out.sales_factor = Number.parseFloat(salesFactor) || undefined;
    return out;
  }

  function variantBody(parent: Product, v: typeof nv) {
    return {
      name: `${parent.name} ${v.name.trim()}`,
      variant_of: parent.id,
      variant_name: v.name.trim(),
      category: parent.category ?? "",
      price_cents: toCents(v.price) || parent.price_cents,
      sku: v.sku.trim(),
      barcode: v.barcode.trim(),
      track_inventory: parent.track_inventory,
      on_hand_qty: Number.parseFloat(v.stock || "0") || 0,
      // A variant is counted, bought and sold in its main product's units.
      ...(parent.base_uom_id
        ? {
            base_uom_id: parent.base_uom_id,
            purchase_uom_id: parent.purchase_uom_id,
            purchase_factor: parent.purchase_factor,
            sales_uom_id: parent.sales_uom_id,
            sales_factor: parent.sales_factor,
          }
        : {}),
    };
  }

  async function addVariant() {
    if (!nv.name.trim()) return;
    if (!product) {
      setPending((ps) => [...ps, nv]);
      setNv({ name: "", price: "", sku: "", barcode: "", stock: "" });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const v = await api.post<Product>("/api/inventory/products", variantBody(product, nv));
      setVariants((vs) => [...vs, v].sort((a, b) => a.price_cents - b.price_cents));
      setNv({ name: "", price: "", sku: "", barcode: "", stock: "" });
      onSaved([v as unknown as RecordRow]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the variant.");
    } finally {
      setBusy(false);
    }
  }

  const shown = preview ?? photo;
  return (
    <Modal
      wide
      title={isNew ? "New product" : product!.name}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      {error ? <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div> : null}
      <div className="inv-editor">
        <div className="inv-editor-photo">
          <span className="inv-card-photo">
            {shown ? <img src={shown} alt="" /> : <span className="inv-card-initials">+</span>}
          </span>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={(e) => pickFile(e.target.files?.[0])} />
          <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()}>
            {shown ? "Replace photo" : "Add photo"}
          </Button>
          {shown ? (
            <Button variant="ghost" size="sm" onClick={dropPhoto} disabled={busy}>
              Remove photo
            </Button>
          ) : null}
          <p className="field-label">A clear shot on a plain background. Resized before upload.</p>
        </div>
        <div className="inv-fields">
          <div className="wide">
            <FieldWrap label="Name" required>
              <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus={isNew} />
            </FieldWrap>
          </div>
          <FieldWrap label="Category">
            <Input list="inv-categories" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Groceries" />
            <datalist id="inv-categories">
              {categories.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </FieldWrap>
          <FieldWrap label={variants.length ? "Price (variants have their own)" : "Price"}>
            <Input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="SKU">
            <Input value={sku} onChange={(e) => setSku(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Barcode">
            <Input value={barcode} onChange={(e) => setBarcode(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Cost">
            <Input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Tax type">
            <Select value={taxCode} onChange={(e) => setTaxCode(e.target.value)}>
              <option value="">
                Business default{defaultRate ? ` (${defaultRate.code} · ${defaultRate.rate_bp / 100}%)` : ""}
              </option>
              {rates.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.code} · {r.name} ({r.rate_bp / 100}%)
                </option>
              ))}
            </Select>
          </FieldWrap>
          <FieldWrap label="eTIMS item classification">
            <Input
              inputMode="numeric"
              name="etims-item-class"
              autoComplete="off"
              value={itemClass}
              maxLength={10}
              onChange={(e) => setItemClass(e.target.value.replace(/\D/g, ""))}
              placeholder="KRA code, e.g. 5022110801"
            />
          </FieldWrap>
          <FieldWrap label="eTIMS packaging">
            <Select value={pkgUnit} onChange={(e) => setPkgUnit(e.target.value)}>
              {Object.entries(PACKAGING_UNITS).map(([code, label]) => (
                <option key={code} value={code}>
                  {code} · {label}
                </option>
              ))}
            </Select>
          </FieldWrap>
          {base ? (
            <div className="wide inv-units">
              <div className="field-label" style={{ fontWeight: 600 }}>Units</div>
              <UnitRow label="Stock kept in" units={units} value={base.id} onChange={setBaseId} />
              <UnitRow
                label="Bought in"
                units={units}
                value={purchaseUnit?.id ?? base.id}
                onChange={(id) => {
                  setPurchaseId(id);
                  setPurchaseFactor("");
                }}
                base={base}
                factor={purchaseFactor}
                onFactor={setPurchaseFactor}
              />
              <UnitRow
                label="Sold in"
                units={units}
                value={salesUnit?.id ?? base.id}
                onChange={(id) => {
                  setSalesId(id);
                  setSalesFactor("");
                }}
                base={base}
                factor={salesFactor}
                onFactor={setSalesFactor}
              />
              <p className="field-label" style={{ margin: 0 }}>
                Price is per {unitLabel(salesUnit) || "unit"}; cost is per {baseLabel}.
              </p>
            </div>
          ) : null}
          {isNew ? (
            <FieldWrap label={`Stock now (${baseLabel})`}>
              <Input inputMode="decimal" value={startStock} onChange={(e) => setStartStock(e.target.value)} placeholder="0" />
            </FieldWrap>
          ) : (
            <FieldWrap label="In stock">
              <Input value={`${fmtQty(product!.on_hand_qty)} ${unitLabel(unitById.get(product!.base_uom_id ?? ""))}`} disabled />
            </FieldWrap>
          )}
          <label className="wide" style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 15 }}>
            <Checkbox checked={track} onChange={(e) => setTrack(e.target.checked)} /> Track stock for this product
          </label>
          <label className="wide" style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 15 }}>
            <Checkbox checked={online} onChange={(e) => setOnline(e.target.checked)} /> Sell in the online shop
          </label>

          {!isVariant ? (
            <div className="inv-variants">
              <h3 style={{ margin: "0 0 4px", fontSize: 17 }}>Variants</h3>
              <p className="field-label" style={{ margin: "0 0 8px" }}>
                Sizes, flavours or colours sold as one product on the till (e.g. 1 kg, 2 kg). Each has its own price, barcode and stock.
              </p>
              {pending.map((v, i) => (
                <div key={`p${i}`} className="inv-variant-row">
                  <strong>{v.name}</strong>
                  <span>{v.price ? formatMoney(toCents(v.price)) : "same price"}</span>
                  <span className="field-label">{v.barcode || v.sku || "—"}</span>
                  <span className="inv-card-stock">{v.stock ? `${v.stock} to start` : "—"}</span>
                  <Button size="sm" variant="ghost" onClick={() => setPending((ps) => ps.filter((_, j) => j !== i))}>
                    Remove
                  </Button>
                </div>
              ))}
              {variants.map((v) => (
                <div key={v.id} className="inv-variant-row">
                  <strong>{v.variant_name || v.name}</strong>
                  <span>{formatMoney(v.price_cents)}</span>
                  <span className="field-label">{v.sku || v.barcode || "—"}</span>
                  <span className={v.track_inventory && v.on_hand_qty <= 5 ? "inv-card-stock low" : "inv-card-stock"}>
                    {v.track_inventory ? `${v.on_hand_qty} left` : "—"}
                  </span>
                  <span />
                </div>
              ))}
              <div className="inv-variant-row">
                <Input placeholder="Variant, e.g. 2 kg" value={nv.name} onChange={(e) => setNv({ ...nv, name: e.target.value })} />
                <Input placeholder="Price" inputMode="decimal" value={nv.price} onChange={(e) => setNv({ ...nv, price: e.target.value })} />
                <Input placeholder="Barcode" value={nv.barcode} onChange={(e) => setNv({ ...nv, barcode: e.target.value })} />
                <Input placeholder="Stock" inputMode="numeric" value={nv.stock} onChange={(e) => setNv({ ...nv, stock: e.target.value })} />
                <Button size="sm" onClick={addVariant} disabled={busy || !nv.name.trim()}>
                  Add
                </Button>
              </div>
            </div>
          ) : (
            <p className="field-label wide">This is a variant of {all.find((p) => p.id === product!.variant_of)?.name ?? "another product"}.</p>
          )}
        </div>
      </div>
    </Modal>
  );
}

/** One unit choice. With `base`, says how many base units the unit holds:
 * worked out when the two convert (kg and g), typed for a pack (a carton
 * of 24). */
function UnitRow({
  label,
  units,
  value,
  onChange,
  base,
  factor,
  onFactor,
}: {
  label: string;
  units: Unit[];
  value: string;
  onChange: (id: string) => void;
  base?: Unit;
  factor?: string;
  onFactor?: (f: string) => void;
}) {
  const shown = units.filter((u) => u.active || u.id === value);
  const unit = units.find((u) => u.id === value);
  const fixed = base ? fixedFactor(base, unit) : null;
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <span style={{ width: 110 }}>{label}</span>
      <Select value={value} onChange={(e) => onChange(e.target.value)} style={{ flex: "1 1 160px", minWidth: 0 }}>
        {shown.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
            {u.abbreviation && u.abbreviation !== u.name ? ` (${u.abbreviation})` : ""}
          </option>
        ))}
      </Select>
      {base && unit && unit.id !== base.id ? (
        fixed != null ? (
          <span className="field-label">
            1 {unitLabel(unit)} = {fmtQty(fixed)} {unitLabel(base)}
          </span>
        ) : (
          <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            1 {unitLabel(unit)} =
            <Input inputMode="decimal" value={factor ?? ""} onChange={(e) => onFactor?.(e.target.value)} placeholder="24" style={{ width: 80 }} />
            {unitLabel(base)}
          </span>
        )
      ) : null}
    </div>
  );
}
