CREATE TABLE vehicles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id               UUID NOT NULL,
    name                 TEXT NOT NULL,
    plate_number         TEXT NOT NULL DEFAULT '',
    make                 TEXT NOT NULL DEFAULT '',
    model                TEXT NOT NULL DEFAULT '',
    year                 INTEGER,
    vin                  TEXT NOT NULL DEFAULT '',
    fuel_type            TEXT NOT NULL DEFAULT 'gasoline'
        CHECK (fuel_type IN ('gasoline', 'diesel', 'electric', 'hybrid', 'other')),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'retired')),
    odometer             INTEGER NOT NULL DEFAULT 0,
    assigned_driver_name TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_vehicles_org ON vehicles(org_id);
ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicles FORCE ROW LEVEL SECURITY;
CREATE POLICY vehicles_org_isolation ON vehicles
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE drivers (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID NOT NULL,
    name               TEXT NOT NULL,
    email              TEXT NOT NULL DEFAULT '',
    phone              TEXT NOT NULL DEFAULT '',
    license_number     TEXT NOT NULL DEFAULT '',
    license_expires_on DATE,
    status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_drivers_org ON drivers(org_id);
ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE drivers FORCE ROW LEVEL SECURITY;
CREATE POLICY drivers_org_isolation ON drivers
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE maintenance_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    vehicle_id   UUID NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    service_date DATE NOT NULL,
    odometer     INTEGER NOT NULL DEFAULT 0,
    description  TEXT NOT NULL,
    cost_cents   BIGINT NOT NULL DEFAULT 0,
    vendor       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_maintenance_logs_org ON maintenance_logs(org_id);
CREATE INDEX idx_maintenance_logs_vehicle ON maintenance_logs(vehicle_id);
ALTER TABLE maintenance_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY maintenance_logs_org_isolation ON maintenance_logs
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE fuel_logs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    vehicle_id UUID NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    fill_date  DATE NOT NULL,
    odometer   INTEGER NOT NULL DEFAULT 0,
    quantity   INTEGER NOT NULL DEFAULT 0,
    cost_cents BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX idx_fuel_logs_org ON fuel_logs(org_id);
CREATE INDEX idx_fuel_logs_vehicle ON fuel_logs(vehicle_id);
ALTER TABLE fuel_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE fuel_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY fuel_logs_org_isolation ON fuel_logs
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
