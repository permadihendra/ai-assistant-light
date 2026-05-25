-- Fix reminder date format: convert ISO 8601 → SQLite compatible
-- ISO: '2026-05-25T02:24:42.045814+00:00'
-- SQLite: '2026-05-25 02:24:42'
-- (The ISO format breaks SQLite string comparisons in the scheduler query,
--  causing ALL reminders to be invisible to the scheduler.)

UPDATE reminders
SET remind_at = REPLACE(substr(remind_at, 1, 19), 'T', ' ')
WHERE remind_at LIKE '%-%T%:%:%';
-- Before: '2026-05-25T02:24:42.045814+00:00'
-- After:  '2026-05-25 02:24:42'
-- (substr strips to 19 chars, REPLACE swaps T→space)
