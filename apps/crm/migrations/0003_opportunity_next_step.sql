-- Cheap equivalent of Odoo's "next activity": a single follow-up date on
-- the opportunity itself instead of a whole activity-scheduling
-- subsystem. Surfaced in the kanban card via the same due-date treatment
-- Task.due_at already gets (see web/src/ui/resource/fieldFormat.ts).
ALTER TABLE opportunities ADD COLUMN next_step_at TIMESTAMPTZ;
