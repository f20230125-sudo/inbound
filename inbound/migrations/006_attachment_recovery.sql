ALTER TABLE opportunities ADD COLUMN content_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE packs ADD COLUMN content_version INTEGER NOT NULL DEFAULT 0;
CREATE TABLE attachment_recoveries (
    id INTEGER PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    attachment_id INTEGER NOT NULL REFERENCES attachments(id),
    message_id INTEGER NOT NULL REFERENCES messages(id),
    revision_id INTEGER NOT NULL REFERENCES opportunity_revisions(id),
    expected_revision_id INTEGER NOT NULL REFERENCES opportunity_revisions(id),
    content_version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    supplier TEXT NOT NULL CHECK(supplier='uzair'),
    recorded_at TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    parse_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    previous_state_json TEXT NOT NULL,
    UNIQUE(attachment_id,sha256)
);
