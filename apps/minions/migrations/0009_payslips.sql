-- Payslips (HR plan phase 2): each payroll line keeps what came off its
-- gross (Kenya: NSSF, SHIF, Housing Levy, PAYE) and what the employer
-- adds, worked out when the run is made; the payout is the net.
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS nssf_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS shif_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS levy_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS paye_cents BIGINT NOT NULL DEFAULT 0;
-- 0 on lines from before payslips: their payout was the gross.
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS net_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS employer_nssf_cents BIGINT NOT NULL DEFAULT 0;
ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS employer_levy_cents BIGINT NOT NULL DEFAULT 0;
