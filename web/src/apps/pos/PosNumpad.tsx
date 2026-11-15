/** The till's keypad. `modes` (Qty / % / Price) sit in the fourth column,
 * as on a counter register; without modes it's a plain amount keypad
 * (opening float, cash tendered, counting the drawer). */
export interface NumpadMode {
  id: string;
  label: string;
}

export function PosNumpad({
  onKey,
  onBackspace,
  modes,
  activeMode,
  onMode,
  disabled,
  allowSign,
}: {
  onKey: (key: string) => void;
  onBackspace: () => void;
  modes?: NumpadMode[];
  activeMode?: string;
  onMode?: (id: string) => void;
  disabled?: boolean;
  allowSign?: boolean;
}) {
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
