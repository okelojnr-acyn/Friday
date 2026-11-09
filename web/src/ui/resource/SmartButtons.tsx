import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { ResourceSpec } from "../../lib/types";
import { getReferenceOptions } from "../../lib/referenceCache";
import { fetchCatalog } from "../../lib/catalog";
import { fetchSchema } from "../../lib/schema";

interface SmartButtonsProps {
  app: string;
  schema: ResourceSpec[];
  spec: ResourceSpec;
  recordId: string;
}

interface ReverseRef {
  targetApp: string;
  target: ResourceSpec;
  fieldName: string;
}

/** Odoo calls these "smart buttons": a small count on a record's form
 * linking to whatever points back at it (a Customer's invoices, a
 * Project's tasks). Derived from every *installed* app's schema, not
 * just the current one -- a reference field is free to point at
 * another app's resource (field.reference is always "app.resource",
 * see ReferenceInput/ListView), so a Customer viewed from Invoicing
 * should still show a "Tickets" button for the Projects app's
 * tickets.customer_id pointing back at it. Any resource, in any app,
 * with a `reference` field pointing at this one gets a button for
 * free -- no per-app wiring beyond declaring that one field. */
export function SmartButtons({ app, schema, spec, recordId }: SmartButtonsProps) {
  const [otherSchemas, setOtherSchemas] = useState<{ app: string; schema: ResourceSpec[] }[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((apps) => apps.filter((a) => a.installed && a.name !== app).map((a) => a.name))
      .then((otherApps) =>
        Promise.all(
          otherApps.map((otherApp) =>
            fetchSchema(otherApp)
              .then((s) => ({ app: otherApp, schema: s }))
              .catch(() => ({ app: otherApp, schema: [] as ResourceSpec[] })),
          ),
        ),
      )
      .then((results) => {
        if (!cancelled) setOtherSchemas(results);
      })
      .catch(() => {
        if (!cancelled) setOtherSchemas([]);
      });
    return () => {
      cancelled = true;
    };
  }, [app]);

  const reverseRefs = useMemo<ReverseRef[]>(() => {
    const allSchemas = [{ app, schema }, ...otherSchemas];
    const refs: ReverseRef[] = [];
    for (const { app: schemaApp, schema: appSchema } of allSchemas) {
      for (const s of appSchema) {
        if (schemaApp === app && s.name === spec.name) continue;
        for (const f of s.fields) {
          if (f.type === "reference" && f.reference === `${app}.${spec.name}`) {
            refs.push({ targetApp: schemaApp, target: s, fieldName: f.name });
          }
        }
      }
    }
    return refs;
  }, [app, schema, otherSchemas, spec.name]);

  if (reverseRefs.length === 0) return null;

  return (
    <div className="smart-buttons">
      {reverseRefs.map((ref) => (
        <SmartButton key={`${ref.targetApp}.${ref.target.name}.${ref.fieldName}`} recordId={recordId} {...ref} />
      ))}
    </div>
  );
}

function SmartButton({ targetApp, target, fieldName, recordId }: ReverseRef & { recordId: string }) {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getReferenceOptions(targetApp, target.name).then((rows) => {
      if (cancelled) return;
      setCount(rows.filter((r) => r[fieldName] === recordId).length);
    });
    return () => {
      cancelled = true;
    };
  }, [targetApp, target.name, fieldName, recordId]);

  return (
    <Link to={`/${targetApp}/${target.name}?${fieldName}=${recordId}`} className="smart-button">
      <span className="smart-button-count">{count ?? "…"}</span>
      <span className="smart-button-label">{target.labelPlural}</span>
    </Link>
  );
}
