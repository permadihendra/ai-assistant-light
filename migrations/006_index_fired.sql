-- Add composite index for the scheduler query:
--   WHERE fired = 0 AND remind_at <= datetime('now', '+2 hours')
-- (fired, remind_at) is more selective than (remind_at, fired) because
-- fired=0 is a high-cardinality filter (vs remind_at range scan).
CREATE INDEX IF NOT EXISTS idx_reminders_fired_due ON reminders(fired, remind_at);
