import { useEffect, useState } from "react";

declare const __BUILD_ID__: string;

/** Friday's screens are a web app that stays open for hours (a till, an
 * admin tab). A release changes the server at once but an open page keeps
 * the code it loaded. This checks /version.json (written at build) when
 * the page comes back into view and every 5 minutes, and offers a reload
 * when a newer build is out. The till never reloads by itself: a cashier
 * may be mid-sale. */
export function NewVersionBanner() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (typeof __BUILD_ID__ === "undefined" || __BUILD_ID__ === "dev") return;
    let stopped = false;
    async function check() {
      try {
        const res = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const { build } = (await res.json()) as { build?: string };
        if (!stopped && build && build !== __BUILD_ID__) setStale(true);
      } catch {
        // offline: check again later
      }
    }
    const onVisible = () => document.visibilityState === "visible" && check();
    check();
    const t = setInterval(check, 5 * 60_000);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (!stale) return null;
  return (
    <div
      role="status"
      style={{
        position: "fixed",
        left: "50%",
        bottom: 16,
        transform: "translateX(-50%)",
        zIndex: 1000,
        display: "flex",
        gap: 12,
        alignItems: "center",
        padding: "10px 14px",
        borderRadius: 12,
        background: "#111",
        color: "#fff",
        fontSize: 15,
        maxWidth: "calc(100vw - 32px)",
      }}
    >
      A new version of Friday is out.
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{ border: 0, borderRadius: 8, padding: "6px 12px", background: "#fff", color: "#111", fontWeight: 600, cursor: "pointer" }}
      >
        Reload
      </button>
    </div>
  );
}
