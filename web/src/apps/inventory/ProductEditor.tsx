import { useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { Product } from "../../lib/inventory";
import { PACKAGING_UNITS } from "../../lib/etims";
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
  const [taxCode, setTaxCode] = useState(product?.tax_code ?? "");
  const [itemClass, setItemClass] = useState(product?.etims_item_class ?? "");
  const [pkgUnit, setPkgUnit] = useState(product?.etims_packaging_unit || "NT");
  const settings = useOrgSettings();
  const rates = settings.tax?.rates ?? [];
  const defaultRate = rates.find((r) => r.code === (settings.tax?.default_code || "B"));
  const [startStock, setStartStock] = useState("");
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
        tax_code: taxCode,
        etims_item_class: itemClass.trim(),
        etims_packaging_unit: pkgUnit,
      };
      let saved = isNew
        ? await api.post<Product>("/api/inventory/products", { ...body, on_hand_qty: Number.parseInt(startStock || "0", 10) || 0 })
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
      on_hand_qty: Number.parseInt(v.stock || "0", 10) || 0,
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
          {isNew ? (
            <FieldWrap label="Stock now">
              <Input inputMode="numeric" value={startStock} onChange={(e) => setStartStock(e.target.value)} placeholder="0" />
            </FieldWrap>
          ) : (
            <FieldWrap label="In stock">
              <Input value={String(product!.on_hand_qty)} disabled />
            </FieldWrap>
          )}
          <label className="wide" style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 15 }}>
            <Checkbox checked={track} onChange={(e) => setTrack(e.target.checked)} /> Track stock for this product
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
