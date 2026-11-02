import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { fetchSchema } from "../lib/schema";
import { listRecords, updateRecord } from "../lib/resourceApi";
import type { RecordRow, ResourceSpec, ViewKind } from "../lib/types";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { ListView } from "../ui/resource/ListView";
import { KanbanView } from "../ui/resource/KanbanView";
import { FormView } from "../ui/resource/FormView";

export function ResourcePage() {
  const { app = "", resource = "" } = useParams();
  const [schema, setSchema] = useState<ResourceSpec[] | null>(null);
  const [records, setRecords] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewKind | null>(null);
  const [editing, setEditing] = useState<RecordRow | "new" | null>(null);

  useEffect(() => {
    setSchema(null);
    setRecords(null);
    setError(null);
    fetchSchema(app)
      .then(setSchema)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load this app"));
  }, [app]);

  const spec = useMemo(() => schema?.find((s) => s.name === resource) ?? null, [schema, resource]);

  useEffect(() => {
    if (!spec) return;
    setView(spec.views.includes("kanban") ? "kanban" : "list");
    listRecords(app, resource)
      .then(setRecords)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load records"));
  }, [spec, app, resource]);

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

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{spec.labelPlural}</h1>
          <nav style={{ display: "flex", gap: 12, marginTop: 8 }}>
            {schema.map((s) => (
              <Link
                key={s.name}
                to={`/${app}/${s.name}`}
                className="field-label"
                style={s.name === resource ? { color: "var(--accent)" } : undefined}
              >
                {s.labelPlural}
              </Link>
            ))}
          </nav>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {nonFormViews.length > 1
            ? nonFormViews.map((v) => (
                <Button key={v} size="sm" variant={view === v ? "primary" : "secondary"} onClick={() => setView(v)}>
                  {v === "kanban" ? <Icon name="kanban" size={14} /> : null} {v}
                </Button>
              ))
            : null}
          <Button variant="primary" size="sm" onClick={() => setEditing("new")}>
            <Icon name="plus" size={14} /> New
          </Button>
        </div>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {!records ? (
        <div className="spinner">Loading...</div>
      ) : view === "kanban" ? (
        <KanbanView spec={spec} records={records} onCardClick={setEditing} onMove={handleMove} />
      ) : (
        <ListView spec={spec} records={records} onRowClick={setEditing} />
      )}

      {editing ? (
        <FormView
          spec={spec}
          app={app}
          record={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
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
