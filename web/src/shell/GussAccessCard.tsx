import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import {
  decideGussVoid,
  getGussAccess,
  gussWebLink,
  linkGussTelegram,
  listGussVoids,
  newGussServiceKey,
  setGussAccess,
  unlinkGussTelegram,
  type GussAccess,
  type GussAccessLevel,
  type GussVoidRequest,
} from "../lib/guss";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FieldWrap, Input, Select } from "../ui/Field";

const LEVELS: { value: GussAccessLevel; label: string }[] = [
  { value: "none", label: "No access" },
  { value: "read", label: "Read only" },
  { value: "write", label: "Read and write" },
];

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  manager: "Manager",
  staff: "Staff",
};

function message(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

/** Void requests from Guss (staff asking for an entry to stop counting),
 * for owners and admins to decide here instead of in Telegram. Nothing
 * is deleted either way: an approved entry stays in Guss's history,
 * marked voided. */
function GussApprovals() {
  const [requests, setRequests] = useState<GussVoidRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  function load() {
    listGussVoids()
      .then((r) => setRequests(r.requests))
      .catch((err) =>
        setError(message(err, "Could not load requests from Guss")),
      );
  }
  useEffect(load, []);

  async function decide(number: number, approve: boolean) {
    setBusy(number);
    setError(null);
    try {
      setReply((await decideGussVoid(number, approve)).reply);
      load();
    } catch (err) {
      setError(message(err, "Could not send the decision"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      style={{
        borderTop: "1px solid var(--border)",
        marginTop: 14,
        paddingTop: 12,
      }}
    >
      <div style={{ fontWeight: 500, marginBottom: 4 }}>
        Waiting for approval
      </div>
      <p className="field-label" style={{ marginBottom: 8 }}>
        Entries staff asked Guss to stop counting. Approved ones stay in
        Guss&apos;s history, marked voided.
      </p>
      {error ? (
        <div className="error-banner" style={{ marginBottom: 8 }}>
          {error}
        </div>
      ) : null}
      {reply ? (
        <div style={{ marginBottom: 8 }}>
          <Badge tone="success">{reply}</Badge>
        </div>
      ) : null}
      {requests === null ? (
        <div className="field-label">Loading...</div>
      ) : requests.length === 0 ? (
        <div className="field-label">Nothing waiting.</div>
      ) : (
        requests.map((r) => (
          <div
            key={r.number}
            style={{
              padding: "8px 0",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ wordBreak: "break-word" }}>{r.entry}</div>
            <div className="field-label" style={{ margin: "4px 0 6px" }}>
              {r.requested_by}: {r.reason}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Button
                size="sm"
                variant="primary"
                disabled={busy !== null}
                onClick={() => decide(r.number, true)}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy !== null}
                onClick={() => decide(r.number, false)}
              >
                Reject
              </Button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

/** Guss inside Friday: which apps Guss may read or change, its key, and
 * who is linked. Each person's Friday role is their role in Guss, so the
 * same chain of command applies in Telegram. */
export function GussAccessCard({ canManage }: { canManage: boolean }) {
  const [data, setData] = useState<GussAccess | null>(null);
  const [draft, setDraft] = useState<Record<string, GussAccessLevel>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [key, setKey] = useState<string | null>(null);

  function load() {
    getGussAccess()
      .then((d) => {
        setData(d);
        setDraft(d.access);
      })
      .catch((err) => setError(message(err, "Could not load Guss access")));
  }
  useEffect(load, []);

  async function run(
    action: () => Promise<unknown>,
    done: string,
    fallback: string,
  ) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      load();
    } catch (err) {
      setError(message(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return error ? <div className="error-banner">{error}</div> : null;
  }

  const changed = data.apps.some(
    (a) => (draft[a] ?? "none") !== (data.access[a] ?? "none"),
  );

  return (
    <Card style={{ marginBottom: 12 }}>
      <div style={{ fontWeight: 500, marginBottom: 4 }}>Guss in your apps</div>
      <p className="field-label" style={{ marginBottom: 12 }}>
        What Guss may do in each app when someone talks to it. People act with
        their own Friday role: owners and admins approve voids, members record
        entries.
      </p>
      {error ? (
        <div className="error-banner" style={{ marginBottom: 10 }}>
          {error}
        </div>
      ) : null}
      {notice ? (
        <div style={{ marginBottom: 10 }}>
          <Badge tone="success">{notice}</Badge>
        </div>
      ) : null}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {data.apps.map((app) => (
          <FieldWrap key={app} label={app}>
            <Select
              value={draft[app] ?? "none"}
              disabled={!canManage || busy}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  [app]: e.target.value as GussAccessLevel,
                }))
              }
            >
              {LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </Select>
          </FieldWrap>
        ))}
      </div>
      {canManage ? (
        <div
          style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}
        >
          <Button
            size="sm"
            variant="primary"
            disabled={!changed || busy}
            onClick={() =>
              run(
                () => setGussAccess(draft),
                "Access saved",
                "Could not save access",
              )
            }
          >
            Save access
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() =>
              run(
                async () => setKey((await newGussServiceKey()).key),
                "New key created",
                "Could not create a key",
              )
            }
          >
            {data.has_service_key ? "Replace Guss key" : "Create Guss key"}
          </Button>
        </div>
      ) : null}
      {key ? (
        <div style={{ marginTop: 10 }}>
          <div className="field-label">
            Shown once. Paste it into Friday Host: Servers, your Guss machine,
            Settings, Friday key. Any older key stopped working just now.
          </div>
          <code
            style={{ display: "block", wordBreak: "break-all", marginTop: 4 }}
          >
            {key}
          </code>
        </div>
      ) : null}

      {canManage ? <GussApprovals /> : null}

      <div
        style={{
          borderTop: "1px solid var(--border)",
          marginTop: 14,
          paddingTop: 12,
        }}
      >
        <div style={{ fontWeight: 500, marginBottom: 4 }}>
          Link your Telegram
        </div>
        {data.bot_username ? (
          <div style={{ marginBottom: 10 }}>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() =>
                run(
                  async () => {
                    // Opened now, while the click still counts, or the
                    // browser blocks it as a pop-up.
                    const tab = window.open("", "_blank");
                    try {
                      const { link } = await gussWebLink();
                      if (tab) tab.location.href = link;
                      else window.location.href = link;
                    } catch (err) {
                      tab?.close();
                      throw err;
                    }
                  },
                  "Telegram opened: press Start in Guss to finish linking",
                  "Could not start linking",
                )
              }
            >
              Link my Telegram
            </Button>
            <p className="field-label" style={{ margin: "6px 0 0" }}>
              Opens @{data.bot_username} in Telegram; press Start there and you're linked.
            </p>
          </div>
        ) : null}
        <p className="field-label" style={{ marginBottom: 8 }}>
          {data.bot_username ? "Or send" : "Send"} /link to your Guss bot and enter the 6-digit code here within 30
          minutes. Pasting the whole message works too.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <FieldWrap label="Code">
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              aria-label="Link code"
              value={code}
              // Digits only, the last 6: "Your code: 123 456" pastes fine.
              // (maxLength used to cut a pasted code before the spaces went.)
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(-6))}
              style={{ width: 120, letterSpacing: "0.15em" }}
            />
          </FieldWrap>
          <Button
            size="sm"
            variant="primary"
            disabled={code.length !== 6 || busy}
            onClick={() =>
              run(
                async () => {
                  await linkGussTelegram(code);
                  setCode("");
                },
                "Telegram linked",
                "Could not link",
              )
            }
          >
            Link
          </Button>
        </div>
        {data.links.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            {data.links.map((l) => (
              <div
                key={l.telegram_id}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "6px 0",
                }}
              >
                <div
                  style={{
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {l.telegram_name || l.telegram_id}{" "}
                  <span className="field-label">({l.email})</span>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Badge tone={l.guss_role ? "neutral" : "danger"}>
                    {ROLE_LABEL[l.guss_role] ?? "Viewer, can't use Guss"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => unlinkGussTelegram(l.telegram_id),
                        "Unlinked",
                        "Could not unlink",
                      )
                    }
                  >
                    Unlink
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </Card>
  );
}
