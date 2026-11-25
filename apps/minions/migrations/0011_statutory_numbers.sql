-- The numbers each monthly return needs (HR plan phase 2): KRA PIN for
-- PAYE and the Housing Levy, ID and NSSF number for NSSF, ID and SHA
-- number for SHIF. Set by whoever handles pay; hidden like pay.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS kra_pin TEXT NOT NULL DEFAULT '';
ALTER TABLE employees ADD COLUMN IF NOT EXISTS national_id TEXT NOT NULL DEFAULT '';
ALTER TABLE employees ADD COLUMN IF NOT EXISTS nssf_number TEXT NOT NULL DEFAULT '';
ALTER TABLE employees ADD COLUMN IF NOT EXISTS sha_number TEXT NOT NULL DEFAULT '';
