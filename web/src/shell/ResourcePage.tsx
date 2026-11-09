import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { fetchSchema } from "../lib/schema";
import { listRecords, updateRecord } from "../lib/resourceApi";
import type { RecordRow, ResourceSpec, ViewKind } from "../lib/types";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { ListView } from "../ui/resource/ListView";
import { KanbanView } from "../ui/resource/KanbanView";
import { FormView } from "../ui/resource/FormView";
import { CUSTOM_CREATE_SCREENS } from "./customCreateScreens";
import { BulkAddProductsPanel } from "../apps/inventory/BulkAddProductsPanel";
import { ImportCsvPanel } from "../ui/resource/ImportCsvPanel";

export function ResourcePage() {
  const { app = "", resource = "" } = useParams();
  const [searchParams] = useSearchParams();
  const [schema, setSchema] = useState<ResourceSpec[] | null>(null);
  const [records, setRecords] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewKind | null>(null);
  const [editing, setEditing] = useState<RecordRow | "new" | null>(null);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [importingCsv, setImportingCsv] = useState(false);

  useEffect(() => {
    setSchema(null);
    setRecords(null);
    setError(null);
    fetchSchema(app)
      .then(setSchema)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load this app"));
  }, [app]);

  // Navigating to a different resource (e.g. a smart button's link) does
  // not unmount this component -- it's the same route with new params --
  // so any open record modal has to be closed by hand, or the next
  // resource's FormView would render bound to the previous resource's
  // record.
  useEffect(() => {
    setEditing(null);
  }, [app, resource]);

  const spec = useMemo(() => schema?.find((s) => s.name === resource) ?? null, [schema, resource]);

  useEffect(() => {
    if (!spec) return;
    setView(spec.views.includes("kanban") ? "kanban" : "list");
    listRecords(app, resource)
      .then(setRecords)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load records"));
  }, [spec, app, resource]);

  // A smart button links here as "?fieldName=recordId" (see SmartButtons.tsx)
  // -- e.g. a Project's "3 Tasks" button lands on /projects/task?project_id=...
  const activeFilter = useMemo(() => {
    if (!spec) return null;
    for (const field of spec.fields) {
      if (field.type !== "reference") continue;
      const value = searchParams.get(field.name);
      if (value) return { field, value };
    }
    return null;
  }, [spec, searchParams]);

  const visibleRecords = useMemo(() => {
    if (!records || !activeFilter) return records;
    return records.filter((r) => r[activeFilter.field.name] === activeFilter.value);
  }, [records, activeFilter]);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!schema) return <div className="page spinner">Loading...</div>;
  if (!spec) return <div className="page empty-state">Unknown resource "{resource}".</div>;

  const nonFormViews = spec.views.filter((v): v is Exclude<ViewKind, "form"> => v !== "form");

  async function handleMove(record: RecordRow, newValue: string) {
    if (!spec || !records) return;
    const groupField = spec.kanbanGroupBy!;
    const prev = records;
    setRecords(records.map((r) => (r.id === record.id ? { ...r, [groupField]: newValue } : r)));
    try {
      await updateRecord(app, spec.name, record.id, { [groupField]: newValue });
    } catch (err) {
      setRecords(prev);
      setError(err instanceof ApiError ? err.message : "Could not move record");
    }
  }

  function handleSaved(saved: RecordRow) {
    setRecords((cur) => {
      if (!cur) return [saved];
      const exists = cur.some((r) => r.id === saved.id);
      return exists ? cur.map((r) => (r.id === saved.id ? saved : r)) : [saved, ...cur];
    });
  }

  function handleBulkSaved(saved: RecordRow[]) {
    setRecords((cur) => [...saved, ...(cur ?? [])]);
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{spec.labelPlural}</h1>
          {activeFilter ? (
            <div className="field-label" style={{ marginTop: 4 }}>
              Filtered by {activeFilter.field.label} ·{" "}
              <Link to={`/${app}/${resource}`} style={{ color: "var(--accent)" }}>
                Clear
              </Link>
            </div>
          ) : null}
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            {schema.map((s) => (
              <Link
                key={s.name}
                to={`/${app}/${s.name}`}
                className={`btn btn-sm btn-pill ${s.name === resource ? "btn-primary" : "btn-secondary"}`}
              >
                {s.labelPlural}
              </Link>
            ))}
          </nav>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {nonFormViews.length > 1
            ? nonFormViews.map((v) => (
                <Button
                  key={v}
                  size="sm"
                  className="btn-pill"
                  variant={view === v ? "primary" : "secondary"}
                  onClick={() => setView(v)}
                >
                  {v === "kanban" ? <Icon name="kanban" size={14} /> : null} {v}
                </Button>
              ))
            : null}
          {app === "inventory" && resource === "product" ? (
            <Button variant="secondary" size="sm" className="btn-pill" onClick={() => setBulkAdding(true)}>
              <Icon name="barcode" size={14} /> Bulk add
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" className="btn-pill" onClick={() => setImportingCsv(true)}>
            <Icon name="upload" size={14} /> Import CSV
          </Button>
          <Button variant="primary" size="sm" className="btn-pill" onClick={() => setEditing("new")}>
            <Icon name="plus" size={14} /> New
          </Button>
        </div>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {!visibleRecords ? (
        <div className="spinner">Loading...</div>
      ) : view === "kanban" ? (
        <KanbanView spec={spec} records={visibleRecords} onCardClick={setEditing} onMove={handleMove} />
      ) : (
        <ListView spec={spec} records={visibleRecords} onRowClick={setEditing} />
      )}

      {editing === "new" && CUSTOM_CREATE_SCREENS[`${app}.${resource}`] ? (
        (() => {
          const CustomCreate = CUSTOM_CREATE_SCREENS[`${app}.${resource}`];
          return <CustomCreate onClose={() => setEditing(null)} onSaved={handleSaved} />;
        })()
      ) : editing ? (
        <FormView
          spec={spec}
          app={app}
          schema={schema}
          record={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      ) : null}

      {bulkAdding ? (
        <BulkAddProductsPanel onClose={() => setBulkAdding(false)} onSaved={handleBulkSaved} />
      ) : null}

      {importingCsv ? (
        <ImportCsvPanel
          spec={spec}
          app={app}
          onClose={() => setImportingCsv(false)}
          onImported={handleBulkSaved}
        />
      ) : null}
    </div>
  );
}

export function AppIndexRedirect() {
  const { app = "" } = useParams();
  const [firstResource, setFirstResource] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    fetchSchema(app)
      .then((spec) => setFirstResource(spec[0]?.name ?? null))
      .catch(() => setFirstResource(null));
  }, [app]);

  if (firstResource === undefined) return <div className="page spinner">Loading...</div>;
  if (firstResource === null) return <div className="page empty-state">This app has nothing to show yet.</div>;
  return <Navigate to={`/${app}/${firstResource}`} replace />;
}
