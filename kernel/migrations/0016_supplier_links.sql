-- The supplier page (plan 12.6 / 12.8 step 7): a supplier opens a link,
-- gets an email code at the address on the link, and sees only their own
-- purchase orders. supplier_id is Inventory's suppliers.id (another
-- schema, so no foreign key).
CREATE TABLE core.supplier_links (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES core.orgs(id) ON DELETE CASCADE,
    supplier_id   UUID NOT NULL,
    supplier_name TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_by    UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ
);
CREATE INDEX supplier_links_org_supplier ON core.supplier_links (org_id, supplier_id);

-- The supplier's email codes: one purpose per link ("supplier:<link id>"),
-- so a code works only on the link it was asked for.
ALTER TABLE core.otp_codes DROP CONSTRAINT otp_codes_purpose_check;
ALTER TABLE core.otp_codes ADD CONSTRAINT otp_codes_purpose_check
    CHECK (purpose IN ('signup', 'login', 'invite') OR purpose LIKE 'supplier:%');
