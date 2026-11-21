-- People, roles and access, step 1 (plan section 12.8, 2026-11-22).
--
-- Roles: owner > admin > branch_manager > team_leader > member > viewer.
-- "member" stays the stored name for staff (shown as "Staff"), so every
-- existing check keeps working.
ALTER TABLE core.memberships DROP CONSTRAINT IF EXISTS memberships_role_check;
ALTER TABLE core.memberships ADD CONSTRAINT memberships_role_check
    CHECK (role IN ('owner', 'admin', 'branch_manager', 'team_leader', 'member', 'viewer'));

-- What jobs a person does (cashier, warehouse, logistics, purchasing,
-- sales, accounting, hr), who they report to, and their staff ID: a label
-- for finding them (badge, payslip), never proof of who they are.
ALTER TABLE core.memberships ADD COLUMN perms TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE core.memberships ADD COLUMN reports_to UUID;
ALTER TABLE core.memberships ADD COLUMN staff_id TEXT;
-- reports_to is checked by the API (a member of the same org, no loops)
-- and cleared when that person leaves; no foreign key, since Postgres 14
-- (customers' own servers) can't null one column of a composite key.
CREATE UNIQUE INDEX memberships_staff_id ON core.memberships (org_id, staff_id);

-- Staff IDs: the business's first three letters and a running number
-- (FRI-0001), given to every new membership by the database itself so no
-- sign-up or invite path can miss it.
ALTER TABLE core.orgs ADD COLUMN staff_seq INT NOT NULL DEFAULT 0;

CREATE FUNCTION core.next_staff_id(p_org UUID) RETURNS TEXT AS $$
DECLARE
    n INT;
    prefix TEXT;
BEGIN
    UPDATE core.orgs SET staff_seq = staff_seq + 1 WHERE id = p_org RETURNING staff_seq, name INTO n, prefix;
    prefix := upper(left(regexp_replace(coalesce(prefix, ''), '[^A-Za-z]', '', 'g'), 3));
    IF prefix = '' THEN
        prefix := 'STF';
    END IF;
    RETURN prefix || '-' || lpad(n::text, 4, '0');
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION core.memberships_staff_id() RETURNS trigger AS $$
BEGIN
    IF NEW.staff_id IS NULL OR NEW.staff_id = '' THEN
        NEW.staff_id := core.next_staff_id(NEW.org_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER memberships_staff_id BEFORE INSERT ON core.memberships
    FOR EACH ROW EXECUTE FUNCTION core.memberships_staff_id();

-- Existing people, oldest first.
DO $$
DECLARE
    m RECORD;
BEGIN
    FOR m IN SELECT org_id, user_id FROM core.memberships WHERE staff_id IS NULL ORDER BY org_id, created_at LOOP
        UPDATE core.memberships SET staff_id = core.next_staff_id(m.org_id)
        WHERE org_id = m.org_id AND user_id = m.user_id;
    END LOOP;
END $$;

-- Locations: the business's stores, warehouses and offices. Each business
-- starts with "Main". A person with no locations listed works at all of
-- them (a one-shop business needs no set-up); owners and admins always do.
CREATE TABLE core.locations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'store' CHECK (kind IN ('store', 'warehouse', 'office', 'other')),
    address     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);
INSERT INTO core.locations (org_id, name) SELECT id, 'Main' FROM core.orgs;

CREATE FUNCTION core.orgs_main_location() RETURNS trigger AS $$
BEGIN
    INSERT INTO core.locations (org_id, name) VALUES (NEW.id, 'Main');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER orgs_main_location AFTER INSERT ON core.orgs
    FOR EACH ROW EXECUTE FUNCTION core.orgs_main_location();

CREATE TABLE core.membership_locations (
    org_id      UUID NOT NULL,
    user_id     UUID NOT NULL,
    location_id UUID NOT NULL REFERENCES core.locations(id) ON DELETE CASCADE,
    PRIMARY KEY (org_id, user_id, location_id),
    FOREIGN KEY (org_id, user_id) REFERENCES core.memberships (org_id, user_id) ON DELETE CASCADE
);
