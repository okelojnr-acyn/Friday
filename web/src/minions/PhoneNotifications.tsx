import { useEffect, useState } from "react";
import { pushState, turnOffPush, turnOnPush, type PushState } from "../lib/phonePush";
import { Button } from "../ui/Button";

const SAYS: Record<PushState, string> = {
  on: "On for this phone. Tasks, claims and meetings that need you show up even when Minions is closed.",
  off: "Get tasks, claims and meetings that need you on this phone, even when Minions is closed.",
  blocked: "Notifications are blocked for this app. Allow them in the phone's settings.",
  "needs-install": "On an iPhone: tap Share, then Add to Home Screen, and open Minions from there to turn these on.",
  unsupported: "This browser can't show notifications. Telegram (Guss) still tells you.",
};

/** Me > Phone notifications: on or off for this phone. */
export function PhoneNotifications() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    pushState()
      .then(setState)
      .catch(() => setState("unsupported"));
  }, []);

  async function flip() {
    setBusy(true);
    setProblem(null);
    try {
      if (state === "on") await turnOffPush();
      else await turnOnPush();
      setState(await pushState());
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Could not change notifications");
      setState(await pushState().catch(() => "unsupported" as const));
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;
  return (
    <section className="card card-padded" aria-label="Phone notifications" style={{ display: "grid", gap: 10 }}>
      <h2 className="minions-h2">Phone notifications</h2>
      <p className="field-label" style={{ margin: 0 }}>
        {SAYS[state]}
      </p>
      {problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      {state === "on" || state === "off" ? (
        <Button variant={state === "on" ? "ghost" : "primary"} disabled={busy} onClick={flip}>
          {busy ? "One moment…" : state === "on" ? "Turn off on this phone" : "Turn on phone notifications"}
        </Button>
      ) : null}
    </section>
  );
}
