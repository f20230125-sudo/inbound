CREATE TABLE snapshots (
    version INTEGER PRIMARY KEY, imported_at TEXT NOT NULL,
    latest_message_at TEXT, run_id INTEGER REFERENCES runs(id)
);
CREATE TABLE category_history (
    id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES messages(id),
    previous_category TEXT NOT NULL, category TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE review_events (
    id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    revision_id INTEGER NOT NULL REFERENCES opportunity_revisions(id), pack_id TEXT,
    action TEXT NOT NULL, created_at TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}'
);
ALTER TABLE runs ADD COLUMN stage TEXT;
ALTER TABLE runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'local';
ALTER TABLE runs ADD COLUMN operation_key TEXT;
ALTER TABLE runs ADD COLUMN opportunity_id INTEGER;
ALTER TABLE runs ADD COLUMN revision_id INTEGER;
ALTER TABLE runs ADD COLUMN pack_id TEXT;
ALTER TABLE runs ADD COLUMN source_type TEXT;
CREATE UNIQUE INDEX active_operation ON runs(operation_key)
    WHERE status='running' AND operation_key IS NOT NULL;
