import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { gussChat, gussReport, gussStatus, listGussVoids } from "../lib/guss";
import { useMyPermissions } from "../lib/permissions";
import { Icon } from "./Icon";

type Line = { from: "you" | "guss" | "error"; text: string };

// The browser's own speech-to-text (Chrome, Edge, Safari). Hosted Guss
// images aren't built with Whisper, so voice is turned into text here and
// sent like typing. Firefox has none: the mic button just doesn't show.
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
}
type RecognitionCtor = new () => Recognition;
function speechRecognition(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

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

const REPORTS = ["day", "week", "month"] as const;

// The widget's own words in English or Indonesian, by the browser's
// language (Guss answers in the shop's language either way).
const TEXT = {
  en: {
    reports: { day: "Today", week: "This week", month: "This month" },
    reportAsk: "Report",
    role: "Guss, shop assistant",
    sub: "Records sales, stock and expenses",
    close: "Close Guss",
    open: "Open Guss, shop assistant",
    intro: "Tell Guss what happened, the way you'd text it:",
    examples: ["sold 3 bags of rice at 120", "paid 500 for transport", "restocked 20 sodas"],
    undo: "Say “undo” right after to take the last entry back.",
    answering: "Guss is answering",
    reportsGroup: "Sales reports",
    clear: "Clear",
    listening: "Listening…",
    message: "Message Guss",
    stop: "Stop listening",
    speak: "Speak instead of typing",
    speakTitle: "Speak",
    stopTitle: "Listening… tap to stop",
    send: "Send",
    viewer: "Viewers can see reports. Ask an admin to record entries.",
    micBlocked: "Microphone blocked. Allow it in the browser's address bar to speak to Guss.",
    noAnswer: "Guss didn't answer. Try again in a moment.",
    quickGroup: "Quick entries",
    quick: { sell: "Sold…", stock: "Restocked…", paid: "Paid…" },
    prefill: { sell: "sold ", stock: "restocked ", paid: "paid " },
    approvals: "Approvals",
    noApprovals: "No void requests are waiting.",
    approvalsWhere: "Approve or reject them in Apps & integrations, Guss.",
  },
  id: {
    reports: { day: "Hari ini", week: "Minggu ini", month: "Bulan ini" },
    reportAsk: "Laporan",
    role: "Guss, asisten toko",
    sub: "Mencatat penjualan, stok, dan pengeluaran",
    close: "Tutup Guss",
    open: "Buka Guss, asisten toko",
    intro: "Ceritakan ke Guss apa yang terjadi, seperti mengirim pesan:",
    examples: ["terjual 3 karung beras @120", "bayar 500 untuk transport", "restok 20 soda"],
    undo: "Ketik “batal” sesudahnya untuk membatalkan catatan terakhir.",
    answering: "Guss sedang menjawab",
    reportsGroup: "Laporan penjualan",
    clear: "Hapus",
    listening: "Mendengarkan…",
    message: "Pesan untuk Guss",
    stop: "Berhenti mendengarkan",
    speak: "Bicara, bukan mengetik",
    speakTitle: "Bicara",
    stopTitle: "Mendengarkan… ketuk untuk berhenti",
    send: "Kirim",
    viewer: "Viewer bisa melihat laporan. Minta admin untuk mencatat.",
    micBlocked: "Mikrofon diblokir. Izinkan di bilah alamat browser untuk bicara ke Guss.",
    noAnswer: "Guss tidak menjawab. Coba lagi sebentar.",
    quickGroup: "Catatan cepat",
    quick: { sell: "Terjual…", stock: "Restok…", paid: "Bayar…" },
    prefill: { sell: "terjual ", stock: "restok ", paid: "bayar " },
    approvals: "Persetujuan",
    noApprovals: "Tidak ada permintaan pembatalan.",
    approvalsWhere: "Setujui atau tolak di Aplikasi & integrasi, Guss.",
  },
};

// Guss gives week and month reports to these Friday roles only.
const LONGER_REPORTS = ["owner", "admin", "branch_manager"];

function widgetText() {
  const lang = typeof navigator === "undefined" ? "" : navigator.language.toLowerCase();
  return lang.startsWith("id") ? TEXT.id : TEXT.en;
}

/**
 * Guss, the shop assistant, as a floating chat on every Friday page:
 * "sold 3 bags of rice at 120" records a sale in Guss's books, "undo"
 * takes it back, and the report buttons summarise sales. Hidden until an
 * admin connects Guss on the Integrations page.
 */
export function GussWidget() {
  const { session } = useAuth();
  const [t] = useState(widgetText);
  const [connected, setConnected] = useState(false);
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<Line[]>(loadLines);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const canWrite = session?.role !== "viewer";
  // What this person does (plan 12.3): null on an older kernel, then
  // everything shows as before and Guss still checks.
  const me = useMyPermissions();
  const reports = !me || LONGER_REPORTS.includes(me.role) ? REPORTS : (["day"] as const);
  const quick = (["sell", "stock", "paid"] as const).filter(
    (k) => !me || (k === "sell" ? Boolean(me.rules["pos.sell"]) : k === "stock" ? Boolean(me.rules["stock.write"]) : true),
  );
  const decides = !me || me.role === "owner" || me.role === "admin";
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<Recognition | null>(null);
  const [canSpeak] = useState(() => typeof window !== "undefined" && speechRecognition() !== null);

  function toggleMic() {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Ctor = speechRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = false;
    rec.continuous = false;
    rec.onresult = (e) => {
      const heard = Array.from(e.results)
        .map((r) => r[0]?.transcript ?? "")
        .join(" ")
        .trim();
      if (heard) setText((t) => (t.trim() ? `${t.trim()} ${heard}` : heard));
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setLines((l) => [...l, { from: "error", text: t.micBlocked }]);
      }
    };
    rec.onend = () => {
      setListening(false);
      inputRef.current?.focus();
    };
    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }

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
      const msg = err instanceof ApiError ? err.message : t.noAnswer;
      setLines((l) => [...l, { from: "error", text: msg }]);
    } finally {
      setBusy(false);
    }
  }

  function prefill(words: string) {
    setText(words);
    inputRef.current?.focus();
  }

  function approvals() {
    void ask(async () => {
      const { requests } = await listGussVoids();
      if (requests.length === 0) return { reply: t.noApprovals };
      const list = requests.map((r) => `${r.number}. ${r.requested_by}: ${r.entry} (${r.reason})`).join("\n");
      return { reply: `${list}\n${t.approvalsWhere}` };
    }, t.approvals);
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
        <section className="guss-panel" role="dialog" aria-label={t.role}>
          <header className="guss-head">
            <span className="guss-avatar" aria-hidden>
              <Icon name="sparkle" size={16} />
            </span>
            <span className="guss-title">
              Guss
              <span className="guss-sub">{t.sub}</span>
            </span>
            <button type="button" className="guss-icon-btn" onClick={() => setOpen(false)} aria-label={t.close}>
              <Icon name="close" size={16} />
            </button>
          </header>

          <div className="guss-lines" ref={listRef} aria-live="polite">
            {lines.length === 0 && (
              <div className="guss-empty">
                <p>{t.intro}</p>
                <ul>
                  {t.examples.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
                <p>{t.undo}</p>
              </div>
            )}
            {lines.map((l, i) => (
              <div key={i} className={`guss-line guss-line-${l.from}`}>
                {l.text}
              </div>
            ))}
            {busy && (
              <div className="guss-line guss-line-guss guss-typing" aria-label={t.answering}>
                <span />
                <span />
                <span />
              </div>
            )}
          </div>

          <div className="guss-reports" role="group" aria-label={t.reportsGroup}>
            {reports.map((w) => (
              <button
                key={w}
                type="button"
                className="guss-chip"
                disabled={busy}
                onClick={() => void ask(() => gussReport(w), `${t.reportAsk}: ${t.reports[w].toLowerCase()}`)}
              >
                {t.reports[w]}
              </button>
            ))}
            {decides && (
              <button type="button" className="guss-chip" disabled={busy} onClick={approvals}>
                {t.approvals}
              </button>
            )}
            {lines.length > 0 && (
              <button type="button" className="guss-chip guss-chip-quiet" onClick={() => setLines([])}>
                {t.clear}
              </button>
            )}
          </div>

          {canWrite && quick.length > 0 && (
            <div className="guss-reports" role="group" aria-label={t.quickGroup}>
              {quick.map((k) => (
                <button key={k} type="button" className="guss-chip guss-chip-quiet" onClick={() => prefill(t.prefill[k])}>
                  {t.quick[k]}
                </button>
              ))}
            </div>
          )}
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
                placeholder={listening ? t.listening : t.examples[0]}
                aria-label={t.message}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              {canSpeak && (
                <button
                  type="button"
                  className={`guss-mic${listening ? " guss-mic-on" : ""}`}
                  onClick={toggleMic}
                  disabled={busy}
                  aria-pressed={listening}
                  aria-label={listening ? t.stop : t.speak}
                  title={listening ? t.stopTitle : t.speakTitle}
                >
                  <Icon name="mic" size={16} />
                </button>
              )}
              <button type="submit" className="guss-send" disabled={busy || !text.trim()} aria-label={t.send}>
                <Icon name="send" size={16} />
              </button>
            </form>
          ) : (
            <p className="guss-readonly">{t.viewer}</p>
          )}
        </section>
      )}

      <button
        type="button"
        className={`guss-fab${open ? " guss-fab-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={open ? t.close : t.open}
      >
        <Icon name={open ? "close" : "sparkle"} size={20} />
        {!open && <span className="guss-fab-label">Guss</span>}
      </button>
    </>
  );
}
