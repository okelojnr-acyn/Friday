-- Parcels (plan 12.2 "deliveries and parcels"; owner, 2026-11-22: Guss
-- scans them in and out). One row per tracking code; every change is an
-- event (who, what, when), which is also the parcel's history.
CREATE TABLE parcels (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    tracking_code   TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    recipient_name  TEXT NOT NULL DEFAULT '',
    recipient_phone TEXT NOT NULL DEFAULT '',
    destination     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'out_for_delivery', 'delivered', 'returned')),
    -- Who has it now (a Friday user id) and where it was last scanned in.
    holder_user_id  TEXT NOT NULL DEFAULT '',
    holder_email    TEXT NOT NULL DEFAULT '',
    location_id     UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, tracking_code)
);
CREATE INDEX idx_parcels_org_holder ON parcels(org_id, holder_user_id);
ALTER TABLE parcels ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcels FORCE ROW LEVEL SECURITY;
CREATE POLICY parcels_org_isolation ON parcels
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE parcel_events (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    parcel_id  UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,
    by_user_id TEXT NOT NULL DEFAULT '',
    by_email   TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_parcel_events_parcel ON parcel_events(parcel_id, at);
ALTER TABLE parcel_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_events FORCE ROW LEVEL SECURITY;
CREATE POLICY parcel_events_org_isolation ON parcel_events
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
