import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { inviteMember, listMembers, removeMember, setMemberRole, type Member } from "../lib/members";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";
import { Avatar } from "../ui/Avatar";
import { initials } from "../ui/resource/fieldFormat";

const INVITABLE_ROLES = ["member", "admin", "viewer"];
const SETTABLE_ROLES = ["owner", "admin", "member", "viewer"];

/** Settings > Members: the org roster, plus inviting new people. Backed
 * entirely by the kernel (kernel/internal/org/members.go,
 * kernel/internal/auth/invites.go) -- there's no per-app concept of a
 * "user" here, membership is core.memberships, the same table every
 * app's JWT role check already reads from.
 *
 * Inviting reuses the exact emailed-one-time-code flow Register already
 * uses (OtpStore, purpose "invite" instead of "signup") -- the invited
 * person finishes joining from the login screen's "Join with an invite"
 * option, not from here; this page only starts that off and shows who's
 * already in.
 */
export function MembersSettingsPage() {
  const { session } = useAuth();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviting, setInviting] = useState(false);
  const [inviteNotice, setInviteNotice] = useState<string | null>(null);

  const canManage = session?.role === "owner" || session?.role === "admin";

  function load() {
    listMembers()
      .then(setMembers)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load members"));
  }

  useEffect(load, []);

  async function sendInvite() {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setError(null);
    setInviteNotice(null);
    try {
      await inviteMember(inviteEmail.trim(), inviteRole);
      setInviteNotice(`Invite sent to ${inviteEmail.trim()} -- they'll get a code by email to finish joining.`);
      setInviteEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send invite");
    } finally {
      setInviting(false);
    }
  }

  async function changeRole(member: Member, role: string) {
    setPendingUserId(member.user_id);
    setError(null);
    try {
      await setMemberRole(member.user_id, role);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change role");
    } finally {
      setPendingUserId(null);
    }
  }

  async function remove(member: Member) {
    setPendingUserId(member.user_id);
    setError(null);
    try {
      await removeMember(member.user_id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove member");
    } finally {
      setPendingUserId(null);
    }
  }

  if (!members) return <div className="page spinner">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Members</h1>
      </div>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {canManage ? (
        <div className="card card-padded" style={{ marginBottom: 16 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>
            Invite someone new
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <FieldWrap label="Email">
              <Input
                type="email"
                placeholder="person@example.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                style={{ width: 240 }}
              />
            </FieldWrap>
            <FieldWrap label="Role">
              <Select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} style={{ width: 140 }}>
                {INVITABLE_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </FieldWrap>
            <Button variant="primary" onClick={sendInvite} disabled={inviting || !inviteEmail.trim()}>
              {inviting ? "Sending..." : "Send invite"}
            </Button>
          </div>
          {inviteNotice ? (
            <div className="field-label" style={{ marginTop: 8 }}>
              {inviteNotice}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>Joined</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const isSelf = m.email === session?.email;
              return (
                <tr key={m.user_id} style={{ cursor: "default" }}>
                  <td>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Avatar label={initials(m.full_name || m.email)} title={m.email} size={26} />
                      <div>
                        <div style={{ fontWeight: 500 }}>{m.full_name || m.email}</div>
                        <div className="field-label">
                          {m.email}
                          {isSelf ? " (you)" : ""}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    {canManage ? (
                      <Select
                        value={m.role}
                        disabled={pendingUserId === m.user_id}
                        onChange={(e) => changeRole(m, e.target.value)}
                        style={{ width: 120 }}
                      >
                        {SETTABLE_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Badge tone="neutral">{m.role}</Badge>
                    )}
                  </td>
                  <td className="field-label">{new Date(m.created_at).toLocaleDateString()}</td>
                  <td style={{ textAlign: "right" }}>
                    {canManage ? (
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={pendingUserId === m.user_id}
                        onClick={() => remove(m)}
                      >
                        Remove
                      </Button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
