import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { gussChat, gussReport, gussStatus } from "../lib/guss";
import { Icon } from "./Icon";

type Line = { from: "you" | "guss" | "error"; text: string };

const STORE_KEY = "friday.guss.lines";
const MAX_LINES = 40;

function loadLines(): Line[] {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Line[]).slice(-MAX_LINES) : [];
  } catch {
    return [];
  }
}

const REPORTS = [
  { window: "day", label: "Today" },
  { window: "week", label: "This week" },
  { window: "month", label: "This month" },
] as const;

/**
 * Guss, the shop assistant, as a floating chat on every Friday page:
 * "sold 3 bags of rice at 120" records a sale in Guss's books, "undo"
 * takes it back, and the report buttons summarise sales. Hidden until an
 * admin connects Guss on the Integrations page.
 */
export function GussWidget() {
  const { session } = useAuth();
  const [connected, setConnected] = useState(false);
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Line[]>(loadLines);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const canWrite = session?.role !== "viewer";

  useEffect(() => {
    let alive = true;
    gussStatus()
      .then((s) => alive && setConnected(s.connected))
      .catch(() => alive && setConnected(false));
    return () => {
      alive = false;
    };
  }, [session?.orgId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(lines.slice(-MAX_LINES)));
    } catch {
      // storage full or blocked: the chat still works, it just won't survive a reload
    }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [lines, open]);

  useEffect(() => {
    if (open && canWrite) inputRef.current?.focus();
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, canWrite]);

  if (!connected || !session) return null;

  async function ask(run: () => Promise<{ reply: string }>, mine?: string) {
    if (busy) return;
    setBusy(true);
    if (mine) setLines((l) => [...l, { from: "you", text: mine }]);
    try {
      const { reply } = await run();
      setLines((l) => [...l, { from: "guss", text: reply }]);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Guss didn't answer. Try again in a moment.";
      setLines((l) => [...l, { from: "error", text: msg }]);
    } finally {
      setBusy(false);
    }
  }

  function send() {
    const t = text.trim();
    if (!t) return;
    setText("");
    void ask(() => gussChat(t), t);
  }

  return (
    <>
      {open && (
        <section className="guss-panel" role="dialog" aria-label="Guss, shop assistant">
          <header className="guss-head">
            <span className="guss-avatar" aria-hidden>
              <Icon name="sparkle" size={16} />
            </span>
            <span className="guss-title">
              Guss
              <span className="guss-sub">Records sales, stock and expenses</span>
            </span>
            <button type="button" className="guss-icon-btn" onClick={() => setOpen(false)} aria-label="Close Guss">
              <Icon name="close" size={16} />
            </button>
          </header>

          <div className="guss-lines" ref={listRef} aria-live="polite">
            {lines.length === 0 && (
              <div className="guss-empty">
                <p>Tell Guss what happened, the way you&apos;d text it:</p>
                <ul>
                  <li>sold 3 bags of rice at 120</li>
                  <li>paid 500 for transport</li>
                  <li>restocked 20 sodas</li>
                </ul>
                <p>Say &ldquo;undo&rdquo; right after to take the last entry back.</p>
              </div>
            )}
            {lines.map((l, i) => (
              <div key={i} className={`guss-line guss-line-${l.from}`}>
                {l.text}
              </div>
            ))}
            {busy && (
              <div className="guss-line guss-line-guss guss-typing" aria-label="Guss is answering">
                <span />
                <span />
                <span />
              </div>
            )}
          </div>

          <div className="guss-reports" role="group" aria-label="Sales reports">
            {REPORTS.map((r) => (
              <button
                key={r.window}
                type="button"
                className="guss-chip"
                disabled={busy}
                onClick={() => void ask(() => gussReport(r.window), `Report: ${r.label.toLowerCase()}`)}
              >
                {r.label}
              </button>
            ))}
            {lines.length > 0 && (
              <button type="button" className="guss-chip guss-chip-quiet" onClick={() => setLines([])}>
                Clear
              </button>
            )}
          </div>

          {canWrite ? (
            <form
              className="guss-form"
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
            >
              <textarea
                ref={inputRef}
                className="guss-input"
                rows={1}
                value={text}
                maxLength={2000}
                placeholder="sold 3 bags of rice at 120"
                aria-label="Message Guss"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <button type="submit" className="guss-send" disabled={busy || !text.trim()} aria-label="Send">
                <Icon name="send" size={16} />
              </button>
            </form>
          ) : (
            <p className="guss-readonly">Viewers can see reports. Ask an admin to record entries.</p>
          )}
        </section>
      )}

      <button
        type="button"
        className={`guss-fab${open ? " guss-fab-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={open ? "Close Guss" : "Open Guss, shop assistant"}
      >
        <Icon name={open ? "close" : "sparkle"} size={20} />
        {!open && <span className="guss-fab-label">Guss</span>}
      </button>
    </>
  );
}
