import { Button } from "../../ui/Button";

/** Save, or why this person can't. */
export function SaveRow({
  canEdit,
  saving,
  onSave,
}: {
  canEdit: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  return canEdit ? (
    <div>
      <Button variant="primary" onClick={onSave} disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </Button>
    </div>
  ) : (
    <p className="field-label">Only owners and admins can change these.</p>
  );
}
