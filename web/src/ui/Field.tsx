import { useState } from "react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

interface FieldWrapProps {
  label: string;
  required?: boolean;
  /** One or two sentences behind a "?" next to the label. */
  hint?: string;
  children: ReactNode;
}

export function FieldWrap({ label, required, hint, children }: FieldWrapProps) {
  const field = (
    <label className="field">
      <span className="field-label">
        {label}
        {required ? <span className="field-required"> *</span> : null}
      </span>
      {children}
    </label>
  );
  // The "?" sits outside the <label>: inside, a click on the label text
  // would press the button instead of focusing the input.
  return hint ? (
    <div className="field-hinted">
      {field}
      <Hint label={label} text={hint} />
    </div>
  ) : (
    field
  );
}

/** A small "?" that shows a short explanation under it: by tap, click or
 * keyboard (never hover-only), read out when it opens, Escape closes. */
export function Hint({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="hint-btn"
        aria-label={`What is ${label}?`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        ?
      </button>
      <p role="status" className="field-hint">
        {open ? text : ""}
      </p>
    </>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="textarea" {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select" {...props} />;
}

export function Checkbox(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" {...props} />;
}
