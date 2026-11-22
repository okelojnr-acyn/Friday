-- A team leader's or manager's PIN approving a staff return at the till
-- (plan 12.2: "refunds and voids: team leader approves team <= limit").
ALTER TABLE core.pos_pin_events DROP CONSTRAINT IF EXISTS pos_pin_events_kind_check;
ALTER TABLE core.pos_pin_events ADD CONSTRAINT pos_pin_events_kind_check CHECK (kind IN (
    'signin', 'wrong_pin', 'locked', 'unlocked', 'pin_set', 'pin_cleared', 'device_enrolled', 'device_revoked', 'approved'));
