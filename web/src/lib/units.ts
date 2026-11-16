import { useEffect, useState } from "react";
import { api } from "./api";

/** Units of measure (apps/inventory/app/uom.py). Stock is kept in each
 * product's base unit; one purchase unit holds purchase_factor base units,
 * one sales unit sales_factor. */
export interface Unit {
  id: string;
  name: string;
  abbreviation: string;
  code: string;
  category: "unit" | "weight" | "volume" | "length" | "area" | "time";
  /** Size against the category's reference; null for a pack (carton). */
  ratio: number | null;
  etims_code: string;
  active: boolean;
  products_using: number;
}

export const CATEGORY_LABEL: Record<Unit["category"], string> = {
  unit: "Count and packs",
  weight: "Weight",
  volume: "Volume",
  length: "Length",
  area: "Area",
  time: "Time",
};

let cache: Unit[] | null = null;
let inflight: Promise<Unit[]> | null = null;

export function loadUnits(force = false): Promise<Unit[]> {
  if (cache && !force) return Promise.resolve(cache);
  if (!inflight || force) {
    inflight = api
      .get<Unit[]>("/api/inventory/units_of_measure")
      .then((u) => (cache = u))
      .catch(() => cache ?? [])
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useUnits(): { units: Unit[]; byId: Map<string, Unit>; reload: () => void } {
  const [units, setUnits] = useState<Unit[]>(cache ?? []);
  useEffect(() => {
    loadUnits().then(setUnits);
  }, []);
  return {
    units,
    byId: new Map(units.map((u) => [u.id, u])),
    reload: () => loadUnits(true).then(setUnits),
  };
}

export const createUnit = (body: { name: string; abbreviation: string; category: string; ratio: number | null; etims_code: string }) =>
  api.post<Unit>("/api/inventory/units_of_measure", body);

export const patchUnit = (id: string, body: Partial<Pick<Unit, "active" | "name" | "abbreviation" | "etims_code">>) =>
  api.patch<Unit>(`/api/inventory/units_of_measure/${id}`, body);

/** Base units in one `unit`, when the two convert by themselves. */
export function fixedFactor(base: Unit | undefined, unit: Unit | undefined): number | null {
  if (!base || !unit) return null;
  if (base.id === unit.id) return 1;
  if (base.ratio != null && unit.ratio != null && base.category === unit.category) {
    return Math.round((unit.ratio / base.ratio) * 1e6) / 1e6;
  }
  return null;
}

/** 0.5, 12, 2.25: no trailing zeros. */
export function fmtQty(n: number): string {
  return String(Math.round(n * 1000) / 1000);
}

export function unitLabel(u: Unit | undefined): string {
  return u ? u.abbreviation || u.name : "";
}
