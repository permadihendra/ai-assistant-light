-- FTS5 full-text search for messages and notes
-- Uses external content tables (reads from source tables directly)
-- Triggers keep FTS indexes in sync on INSERT/UPDATE/DELETE

-- ── Messages FTS ────────────────────────────────────────

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    chat_id UNINDEXED,
    text,
    username UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, chat_id, text, username)
    VALUES (new.id, new.chat_id, new.text, new.username);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, chat_id, text, username)
    VALUES ('delete', old.id, old.chat_id, old.text, old.username);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, chat_id, text, username)
    VALUES ('delete', old.id, old.chat_id, old.text, old.username);
    INSERT INTO messages_fts(rowid, chat_id, text, username)
    VALUES (new.id, new.chat_id, new.text, new.username);
END;

-- ── Notes FTS ───────────────────────────────────────────

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    chat_id UNINDEXED,
    text,
    content='notes',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS notes_fts_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, chat_id, text)
    VALUES (new.id, new.chat_id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS notes_fts_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, chat_id, text)
    VALUES ('delete', old.id, old.chat_id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS notes_fts_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, chat_id, text)
    VALUES ('delete', old.id, old.chat_id, old.text);
    INSERT INTO notes_fts(rowid, chat_id, text)
    VALUES (new.id, new.chat_id, new.text);
END;

-- ── Rebuild indexes for existing data ───────────────────

INSERT INTO messages_fts(messages_fts) VALUES('rebuild');
INSERT INTO notes_fts(notes_fts) VALUES('rebuild');
