import type { FieldSpec } from "../../lib/types";
import { Checkbox, Input, Select, Textarea } from "../Field";
import { ReferenceInput } from "./ReferenceInput";

interface FieldInputProps {
  field: FieldSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}

/** Renders the right control for a FieldSpec. Operates on "edit-friendly"
 * values (strings for text/number/date inputs, booleans for checkboxes);
 * FormView converts to/from the wire representation (e.g. currency's
 * cents <-> dollar string) at load/submit time -- see fieldFormat.ts. */
export function FieldInput({ field, value, onChange }: FieldInputProps) {
  switch (field.type) {
    case "textarea":
      return <Textarea value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} required={field.required} />;
    case "boolean":
      return (
        <div className="checkbox-row">
          <Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        </div>
      );
    case "number":
      return (
        <Input
          type="number"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "currency":
      return (
        <Input
          type="number"
          step="0.01"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "date":
      return (
        <Input
          type="date"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "datetime":
      return (
        <Input
          type="datetime-local"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "select":
      return (
        <Select value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} required={field.required}>
          <option value="" disabled>
            Select...
          </option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
      );
    case "email":
      return (
        <Input
          type="email"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "phone":
      return (
        <Input
          type="tel"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
    case "reference":
      return <ReferenceInput field={field} value={value} onChange={onChange} />;
    case "text":
    default:
      return (
        <Input
          type="text"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          required={field.required}
        />
      );
  }
}
