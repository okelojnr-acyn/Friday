import { useEffect, useState } from "react";
import { Button } from "../../ui/Button";

const FLAG = "friday.saved";

/** Saves that reload the page (every screen reads settings once) still
 * answer the click: the SaveRow after the reload says "Saved". */
export function reloadSaved() {
  try {
    sessionStorage.setItem(FLAG, "1");
  } catch {
    /* private mode: the reload alone will do */
  }
  window.location.reload();
}

function takeFlag(): boolean {
  try {
    const had = sessionStorage.getItem(FLAG) === "1";
    sessionStorage.removeItem(FLAG);
    return had;
  } catch {
    return false;
  }
}

/** Save, or why this person can't. "Saved ✓" answers a save that worked. */
export function SaveRow({
  canEdit,
  saving,
  saved = false,
  onSave,
}: {
  canEdit: boolean;
  saving: boolean;
  saved?: boolean;
  onSave: () => void;
}) {
  const [flash, setFlash] = useState(takeFlag);
  useEffect(() => {
    if (saved) setFlash(true);
  }, [saved]);
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(false), 2500);
    return () => clearTimeout(t);
  }, [flash]);

  return canEdit ? (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Button variant="primary" onClick={onSave} disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </Button>
      <span role="status" className="field-label" style={{ color: "var(--success, #1f8a4c)", fontWeight: 600 }}>
        {flash && !saving ? "Saved ✓" : ""}
      </span>
    </div>
  ) : (
    <p className="field-label">Only owners and admins can change these.</p>
  );
}
