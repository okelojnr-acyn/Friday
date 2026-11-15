import { useEffect, useState } from "react";
import { ApiError } from "./api";
import { KERNEL_URL } from "./runtimeConfig";
import { loadSession } from "./session";

/** Product photos (apps/inventory: /products/{id}/image). Photos need the
 * sign-in token, so they're fetched rather than put in an <img src>, and
 * kept in the browser's Cache Storage under the photo's sha: a till that
 * starts offline still shows its shelf, and a changed photo has a new
 * key. */

const CACHE = "friday-product-images-v1";
const memory = new Map<string, string>(); // key -> object URL
const inflight = new Map<string, Promise<string | null>>();

function imagePath(id: string, sha: string) {
  return `/api/inventory/products/${id}/image?v=${sha}`;
}

async function load(id: string, sha: string): Promise<string | null> {
  const key = `${id}:${sha}`;
  const cacheKey = new Request(`${location.origin}/__product-images/${id}/${sha}`);
  let blob: Blob | null = null;
  try {
    const cache = "caches" in window ? await caches.open(CACHE) : null;
    const hit = cache ? await cache.match(cacheKey) : undefined;
    if (hit) {
      blob = await hit.blob();
    } else {
      const token = loadSession()?.token;
      const res = await fetch(`${KERNEL_URL}${imagePath(id, sha)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return null;
      blob = await res.blob();
      await cache?.put(cacheKey, new Response(blob, { headers: { "Content-Type": blob.type } }));
    }
  } catch {
    return null; // offline and not cached yet: the tile shows the name
  }
  const url = URL.createObjectURL(blob);
  memory.set(key, url);
  return url;
}

/** The product's photo as an object URL, or null (no photo / not loaded). */
export function useProductImage(p: { id: string; image_sha?: string }): string | null {
  const sha = p.image_sha ?? "";
  const key = `${p.id}:${sha}`;
  const [url, setUrl] = useState<string | null>(() => (sha ? (memory.get(key) ?? null) : null));
  useEffect(() => {
    if (!sha) {
      setUrl(null);
      return;
    }
    const known = memory.get(key);
    if (known) {
      setUrl(known);
      return;
    }
    let live = true;
    let job = inflight.get(key);
    if (!job) {
      job = load(p.id, sha).finally(() => inflight.delete(key));
      inflight.set(key, job);
    }
    job.then((u) => live && setUrl(u));
    return () => {
      live = false;
    };
  }, [p.id, sha, key]);
  return url;
}

/** Shrinks a photo to fit 512x512 and encodes it as WebP (JPEG where the
 * browser can't), so it's tens of KB, not megabytes. */
export async function shrinkPhoto(file: File, max = 512): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser can't resize photos.");
  ctx.fillStyle = "#fff"; // transparent PNGs get a white background
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  const encode = (type: string) => new Promise<Blob | null>((res) => canvas.toBlob(res, type, 0.82));
  const blob = (await encode("image/webp")) ?? (await encode("image/jpeg"));
  if (!blob) throw new Error("Couldn't encode the photo.");
  return blob.type === "image/webp" || blob.type === "image/jpeg" ? blob : (await encode("image/jpeg"))!;
}

async function send(method: "PUT" | "DELETE", id: string, body?: Blob) {
  const token = loadSession()?.token;
  const res = await fetch(`${KERNEL_URL}/api/inventory/products/${id}/image`, {
    method,
    body,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": body.type } : {}),
    },
  });
  if (!res.ok) {
    const msg = await res
      .json()
      .then((b) => b.detail ?? b.error)
      .catch(() => res.statusText);
    throw new ApiError(res.status, String(msg));
  }
  return res.json() as Promise<{ image_sha: string }>;
}

/** Resizes and uploads a photo; returns the product's new image_sha. */
export async function uploadProductImage(id: string, file: File): Promise<string> {
  return (await send("PUT", id, await shrinkPhoto(file))).image_sha;
}

export async function removeProductImage(id: string): Promise<void> {
  await send("DELETE", id);
}

/** A steady, soft colour per category (shelf stripes, category buttons,
 * placeholder tiles), chosen to sit with Friday's warm palette. */
const CATEGORY_TINTS = [
  { bar: "#e07a35", soft: "rgba(224, 122, 53, 0.14)" }, // amber
  { bar: "#7aa354", soft: "rgba(122, 163, 84, 0.16)" }, // sage
  { bar: "#4f8fb8", soft: "rgba(79, 143, 184, 0.15)" }, // lake
  { bar: "#a0679a", soft: "rgba(160, 103, 154, 0.15)" }, // plum
  { bar: "#c9a43c", soft: "rgba(201, 164, 60, 0.18)" }, // sand
  { bar: "#c95f5f", soft: "rgba(201, 95, 95, 0.14)" }, // clay
  { bar: "#4e9a8f", soft: "rgba(78, 154, 143, 0.15)" }, // teal
  { bar: "#7d7466", soft: "rgba(125, 116, 102, 0.15)" }, // stone
];

/** With `all` (the shop's categories), colours go round the palette in
 * alphabetical order, so a handful of categories never share one. */
export function categoryTint(category: string | undefined, all?: string[]): { bar: string; soft: string } {
  const c = (category ?? "").trim().toLowerCase();
  if (!c) return { bar: "rgba(10, 10, 8, 0.18)", soft: "rgba(10, 10, 8, 0.04)" };
  if (all?.length) {
    const sorted = [...new Set(all.map((x) => x.trim().toLowerCase()).filter(Boolean))].sort();
    const i = sorted.indexOf(c);
    if (i >= 0) return CATEGORY_TINTS[i % CATEGORY_TINTS.length];
  }
  let h = 0;
  for (let i = 0; i < c.length; i++) h = (h * 31 + c.charCodeAt(i)) >>> 0;
  return CATEGORY_TINTS[h % CATEGORY_TINTS.length];
}
