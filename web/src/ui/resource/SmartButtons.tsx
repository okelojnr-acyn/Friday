import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { ResourceSpec } from "../../lib/types";
import { getReferenceOptions } from "../../lib/referenceCache";

interface SmartButtonsProps {
  app: string;
  schema: ResourceSpec[];
  spec: ResourceSpec;
  recordId: string;
}

interface ReverseRef {
  target: ResourceSpec;
  fieldName: string;
}

/** Odoo calls these "smart buttons": a small count on a record's form
 * linking to whatever points back at it (a Customer's invoices, a
 * Project's tasks). Derived entirely from the already-loaded app
 * schema -- any resource with a `reference` field pointing at this one
 * gets a button for free, no per-app wiring. */
export function SmartButtons({ app, schema, spec, recordId }: SmartButtonsProps) {
  const reverseRefs = useMemo<ReverseRef[]>(
    () =>
      schema
        .filter((s) => s.name !== spec.name)
        .flatMap((s) =>
          s.fields
            .filter((f) => f.type === "reference" && f.reference === `${app}.${spec.name}`)
            .map((f) => ({ target: s, fieldName: f.name })),
        ),
    [schema, app, spec.name],
  );

  if (reverseRefs.length === 0) return null;

  return (
    <div className="smart-buttons">
      {reverseRefs.map((ref) => (
        <SmartButton key={`${ref.target.name}.${ref.fieldName}`} app={app} recordId={recordId} {...ref} />
      ))}
    </div>
  );
}

function SmartButton({ app, target, fieldName, recordId }: ReverseRef & { app: string; recordId: string }) {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getReferenceOptions(app, target.name).then((rows) => {
      if (cancelled) return;
      setCount(rows.filter((r) => r[fieldName] === recordId).length);
    });
    return () => {
      cancelled = true;
    };
  }, [app, target.name, fieldName, recordId]);

  return (
    <Link to={`/${app}/${target.name}?${fieldName}=${recordId}`} className="smart-button">
      <span className="smart-button-count">{count ?? "…"}</span>
      <span className="smart-button-label">{target.labelPlural}</span>
    </Link>
  );
}
