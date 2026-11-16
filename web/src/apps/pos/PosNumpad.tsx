import { useEffect, useRef } from "react";

/** The till's keypad. `modes` (Qty / % / Price) sit in the fourth column,
 * as on a counter register; without modes it's a plain amount keypad
 * (opening float, cash tendered, counting the drawer). */
export interface NumpadMode {
  id: string;
  label: string;
}

/** Typing on a physical keyboard drives the keypad: digits (top row or
 * number pad), "." or ",", Backspace; Enter and Escape when given. Keys
 * typed into a text field are left alone. */
export interface NumpadKeyboard {
  onEnter?: () => void;
  onEscape?: () => void;
}

function typingInField(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
}

export function PosNumpad({
  onKey,
  onBackspace,
  modes,
  activeMode,
  onMode,
  disabled,
  allowSign,
  keyboard,
}: {
  onKey: (key: string) => void;
  onBackspace: () => void;
  modes?: NumpadMode[];
  activeMode?: string;
  onMode?: (id: string) => void;
  disabled?: boolean;
  allowSign?: boolean;
  keyboard?: NumpadKeyboard | boolean;
}) {
  const latest = useRef({ onKey, onBackspace, keyboard, disabled });
  latest.current = { onKey, onBackspace, keyboard, disabled };
  const listening = !!keyboard;
  useEffect(() => {
    if (!listening) return;
    function onKeyDown(e: KeyboardEvent) {
      const { onKey, onBackspace, keyboard, disabled } = latest.current;
      if (disabled || e.ctrlKey || e.metaKey || e.altKey || typingInField(e.target)) return;
      const kb = typeof keyboard === "object" ? keyboard : {};
      if (/^[0-9]$/.test(e.key)) onKey(e.key);
      else if (e.key === "." || e.key === "," || e.key === "Decimal") onKey(".");
      else if (e.key === "Backspace") onBackspace();
      else if (e.key === "Enter" && kb.onEnter) kb.onEnter();
      else if (e.key === "Escape" && kb.onEscape) kb.onEscape();
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [listening]);
  const rows = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
  ];
  const key = (k: string) => (
    <button key={k} type="button" className="till-key" disabled={disabled} onClick={() => onKey(k)}>
      {k}
    </button>
  );
  return (
    <div className={`till-numpad${modes ? " with-modes" : ""}`}>
      {rows.map((row, i) => (
        <div className="till-numpad-row" key={i}>
          {row.map(key)}
          {modes ? (
            <button
              type="button"
              className={`till-key till-key-mode${activeMode === modes[i]?.id ? " active" : ""}`}
              disabled={disabled || !modes[i]}
              onClick={() => modes[i] && onMode?.(modes[i].id)}
            >
              {modes[i]?.label}
            </button>
          ) : null}
        </div>
      ))}
      <div className="till-numpad-row">
        {allowSign ? (
          <button type="button" className="till-key till-key-sign" disabled={disabled} onClick={() => onKey("+/-")}>
            +/−
          </button>
        ) : (
          key("00")
        )}
        {key("0")}
        {modes ? key(".") : null}
        <button
          type="button"
          className="till-key till-key-back"
          disabled={disabled}
          onClick={onBackspace}
          aria-label="Delete"
        >
          ⌫
        </button>
      </div>
    </div>
  );
}
