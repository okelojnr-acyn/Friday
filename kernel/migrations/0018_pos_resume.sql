-- A cashier resuming an idle till with their own PIN (plan 20.3): the
-- till locks after 5 minutes; the same cashier's PIN continues.
ALTER TABLE core.pos_pin_events DROP CONSTRAINT IF EXISTS pos_pin_events_kind_check;
ALTER TABLE core.pos_pin_events ADD CONSTRAINT pos_pin_events_kind_check CHECK (kind IN (
    'signin', 'wrong_pin', 'locked', 'unlocked', 'pin_set', 'pin_cleared', 'device_enrolled', 'device_revoked', 'approved', 'resumed'));
