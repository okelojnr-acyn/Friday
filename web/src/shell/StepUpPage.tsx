import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { startAuthentication, type PublicKeyCredentialRequestOptionsJSON } from "@simplewebauthn/browser";
import { KERNEL_URL } from "../lib/runtimeConfig";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";

/** Step-up check (plan 16.4): Guss sends a one-time link before a
 * sensitive action; the person confirms it here with their own passkey.
 * No sign-in needed: the kernel checks the passkey belongs to the person
 * the check was made for. */
export function StepUpPage() {
  const [params] = useSearchParams();
  const code = params.get("c") ?? "";
  const [action, setAction] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "busy" | "done" | "error">("loading");
  const [message, setMessage] = useState("");

  const call = async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`${KERNEL_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers as Record<string, string> | undefined) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error ?? res.statusText);
    }
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  };

  useEffect(() => {
    call<{ action: string; done: boolean; expires_in: number }>(`/auth/step-up?c=${encodeURIComponent(code)}`)
      .then((s) => {
        setAction(s.action);
        if (s.done) setState("done");
        else if (s.expires_in <= 0) {
          setState("error");
          setMessage("This link has expired. Ask Guss again.");
        } else setState("ready");
      })
      .catch((e: Error) => {
        setState("error");
        setMessage(e.message);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  async function confirm() {
    setState("busy");
    setMessage("");
    try {
      const { session_id, publicKey } = await call<{ session_id: string; publicKey: PublicKeyCredentialRequestOptionsJSON }>(
        "/auth/passkey/login-options",
        { method: "POST" },
      );
      const answer = await startAuthentication({ optionsJSON: publicKey });
      await call(`/auth/step-up/verify?c=${encodeURIComponent(code)}&session_id=${session_id}`, {
        method: "POST",
        body: JSON.stringify(answer),
      });
      setState("done");
    } catch (e) {
      setState("ready");
      setMessage(e instanceof Error ? e.message : "Couldn't confirm; try again");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="page-title" style={{ marginBottom: 8 }}>
          Confirm it's you
        </h1>
        {action ? (
          <p style={{ marginBottom: 16 }}>
            Guss is about to do this for you: <strong>{action}</strong>
          </p>
        ) : null}
        {state === "done" ? (
          <p role="status">Confirmed. Go back to the chat and send the same message again.</p>
        ) : state === "ready" || state === "busy" ? (
          <Button variant="primary" onClick={confirm} disabled={state === "busy"} style={{ width: "100%" }}>
            {state === "busy" ? "Waiting for your passkey…" : "Confirm with my passkey"}
          </Button>
        ) : state === "loading" ? (
          <p>Loading…</p>
        ) : null}
        {message ? (
          <p role="alert" className="text-sm text-destructive" style={{ marginTop: 12 }}>
            {message}
          </p>
        ) : null}
      </Card>
    </div>
  );
}
