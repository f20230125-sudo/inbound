ALTER TABLE attachments ADD COLUMN import_root TEXT;
ALTER TABLE attachments ADD COLUMN content_base64 TEXT;
CREATE TABLE opportunities (
    id INTEGER PRIMARY KEY, company TEXT, city TEXT, source_thread_id TEXT NOT NULL,
    provider TEXT NOT NULL, normalized_subject TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('ps_call','direct_apply')),
    status TEXT NOT NULL CHECK(status IN
        ('new','preparing','needs_review','reviewed','submitted_by_me','blocked','skipped')),
    blocked_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE opportunity_revisions (
    id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    message_id INTEGER NOT NULL UNIQUE REFERENCES messages(id), fields_json TEXT NOT NULL,
    local_fields_json TEXT NOT NULL, amendment INTEGER NOT NULL,
    blocked_reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE fields (
    id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    revision_id INTEGER NOT NULL REFERENCES opportunity_revisions(id), name TEXT NOT NULL,
    raw TEXT NOT NULL, normalized TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('found','inferred','unknown','conflicting')),
    source_text TEXT NOT NULL, record_json TEXT NOT NULL, UNIQUE(revision_id,name)
);
CREATE TABLE roles (
    id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    revision_id INTEGER NOT NULL REFERENCES opportunity_revisions(id), title TEXT NOT NULL,
    requirements_json TEXT NOT NULL, source_record_json TEXT NOT NULL
);
CREATE TABLE merge_suggestions (
    id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    candidate_id INTEGER NOT NULL REFERENCES opportunities(id), message_id INTEGER NOT NULL,
    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'needs_review',
    UNIQUE(opportunity_id,candidate_id)
);
CREATE TABLE message_extractions (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id), fields_json TEXT NOT NULL,
    attack_suspected INTEGER NOT NULL, attack_quotes_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
