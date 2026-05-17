-- Add source_text column to reminders — stores original full message
-- so users can reference back when distilled text loses detail

ALTER TABLE reminders ADD COLUMN source_text TEXT DEFAULT '';
