-- Add multi-alert support to reminders table
-- alerts: JSON array of minutes-before, e.g. '[15, 5]'
-- alerts_fired: count of how many alerts have been sent

ALTER TABLE reminders ADD COLUMN alerts TEXT DEFAULT '[15, 5]';
ALTER TABLE reminders ADD COLUMN alerts_fired INTEGER DEFAULT 0;
