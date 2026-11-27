import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { useOrgSettings } from "../../lib/orgSettings";
import { FieldWrap, Input } from "../../ui/Field";
import { SaveRow } from "./SaveRow";

interface Limits {
  team_leader: number;
  branch_manager: number;
}

const toInput = (cents: number) => String(Math.round(cents / 100));
const toCents = (v: string) => Math.round((Number.parseFloat(v) || 0) * 100);

/** Business settings > Approvals: the most a team leader or branch manager
 * may approve on one request (expense claims now; advances and time off
 * later). Above that it goes up their reporting line, then to owners and
 * admins, who have no limit. */
export function ApprovalsSection({ canEdit }: { canEdit: boolean }) {
  const { currency } = useOrgSettings();
  const [leader, setLeader] = useState("");
  const [manager, setManager] = useState("");
  const [loaded, setLoaded] = useState<"yes" | "old" | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<Limits>("/orgs/approval-limits")
      .then((l) => {
        setLeader(toInput(l.team_leader));
        setManager(toInput(l.branch_manager));
        setLoaded("yes");
      })
      .catch(() => setLoaded("old"));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.put("/orgs/approval-limits", {
        team_leader: toCents(leader),
        branch_manager: toCents(manager),
      });
      setSaved(true);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save the limits",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loaded === null)
    return <div className="card card-padded spinner">Loading…</div>;
  if (loaded === "old")
    return (
      <div className="card card-padded">
        Update Friday in Friday Host to set approval limits.
      </div>
    );

  return (
    <div className="card card-padded form-grid">
      {error ? <div className="error-banner">{error}</div> : null}
      <p className="field-label" style={{ margin: 0, maxWidth: "60ch" }}>
        A claim goes to the person the claimant reports to. If it's more than
        their limit, it goes to the next person up, and then to owners and
        admins, who can approve any amount.
      </p>
      <FieldWrap label={`Team leaders approve up to (${currency})`}>
        <Input
          value={leader}
          inputMode="numeric"
          disabled={!canEdit}
          onChange={(e) => setLeader(e.target.value)}
        />
      </FieldWrap>
      <FieldWrap label={`Branch managers approve up to (${currency})`}>
        <Input
          value={manager}
          inputMode="numeric"
          disabled={!canEdit}
          onChange={(e) => setManager(e.target.value)}
        />
      </FieldWrap>
      <SaveRow canEdit={canEdit} saving={saving} saved={saved} onSave={save} />
    </div>
  );
}
