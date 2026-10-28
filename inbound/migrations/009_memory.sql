CREATE TABLE memory_snapshots (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    published_at TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    roots_json TEXT NOT NULL
);
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    identity TEXT NOT NULL UNIQUE,
    origin TEXT NOT NULL CHECK(origin IN ('imported','local')),
    source TEXT NOT NULL CHECK(source IN ('private','synthetic')),
    file TEXT NOT NULL,
    document_json TEXT,
    source_json TEXT,
    source_hash TEXT,
    local_file TEXT,
    base_hash TEXT,
    disabled INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('remembered','disabled','deleted','forgotten')),
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    version INTEGER NOT NULL REFERENCES memory_snapshots(version)
);
CREATE TABLE memory_revisions (
    memory_id TEXT NOT NULL REFERENCES memories(id),
    version INTEGER NOT NULL REFERENCES memory_snapshots(version),
    record_json TEXT,
    PRIMARY KEY(memory_id,version)
);
CREATE TABLE memory_suppressions (
    identity TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id),
    created_at TEXT NOT NULL
);
CREATE TABLE memory_scan_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    error TEXT CHECK(error IS NULL OR error='invalid_snapshot')
);
INSERT INTO memory_scan_state VALUES (1,NULL);
CREATE INDEX memory_revisions_version ON memory_revisions(version);
CREATE TRIGGER domain_memories_insert AFTER INSERT ON memories
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memories_update AFTER UPDATE ON memories
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memories_delete AFTER DELETE ON memories
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_snapshots_insert AFTER INSERT ON memory_snapshots
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_revisions_insert AFTER INSERT ON memory_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_revisions_update AFTER UPDATE ON memory_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_revisions_delete AFTER DELETE ON memory_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_suppressions_insert AFTER INSERT ON memory_suppressions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_memory_suppressions_delete AFTER DELETE ON memory_suppressions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
