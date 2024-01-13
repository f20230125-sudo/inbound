CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO settings VALUES ('paused', '0');
CREATE TABLE messages (
    id INTEGER PRIMARY KEY, provider TEXT NOT NULL, provider_id TEXT NOT NULL,
    thread_id TEXT NOT NULL, sent_at TEXT NOT NULL, received_at TEXT NOT NULL,
    sender TEXT NOT NULL, "to" TEXT NOT NULL, cc TEXT NOT NULL, bcc TEXT NOT NULL,
    subject TEXT NOT NULL, body_text TEXT NOT NULL, attachments_json TEXT NOT NULL,
    labels TEXT NOT NULL, body_exported TEXT NOT NULL, body_complete INTEGER NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('private','synthetic')),
    content_hash TEXT NOT NULL, imported_at TEXT NOT NULL,
    UNIQUE(provider, provider_id)
);
CREATE TABLE message_history (
    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES messages(id),
    content_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL, imported_at TEXT NOT NULL,
    UNIQUE(message_id, content_hash)
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES messages(id),
    filename TEXT NOT NULL, mime TEXT NOT NULL, bytes_path TEXT,
    bytes_available INTEGER NOT NULL, text TEXT,
    parse_status TEXT NOT NULL CHECK(parse_status IN ('parsed','unsupported','unreadable','missing'))
);
CREATE TABLE triage (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id), category TEXT NOT NULL,
    urgency TEXT NOT NULL, reason TEXT NOT NULL, rule_id TEXT NOT NULL,
    source_quote TEXT NOT NULL, confidence REAL NOT NULL,
    corrected_category TEXT, corrected_at TEXT
);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, status TEXT NOT NULL, counts_json TEXT NOT NULL DEFAULT '{}',
    model_calls INTEGER NOT NULL DEFAULT 0, cache_hits INTEGER NOT NULL DEFAULT 0, error TEXT
);
