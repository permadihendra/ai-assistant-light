-- Add type column to messages table to distinguish user vs bot messages
ALTER TABLE messages ADD COLUMN type TEXT NOT NULL DEFAULT 'user';
