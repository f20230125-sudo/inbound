CREATE TABLE agent_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1),
    occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('scout','uzair','system')),
    kind TEXT NOT NULL, run_id INTEGER, correlation_id TEXT,
    entity_type TEXT, entity_id TEXT, revision_id INTEGER, snapshot_version INTEGER,
    phase TEXT NOT NULL CHECK(phase IN ('progress','committed_result')),
    outcome TEXT NOT NULL CHECK(outcome IN ('started','succeeded','blocked','failed','cancelled')),
    facts_json TEXT NOT NULL CHECK(json_valid(facts_json)),
    source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json)),
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL CHECK(source IN ('private','synthetic'))
);
CREATE INDEX agent_steps_run ON agent_steps(run_id,id);
CREATE INDEX agent_steps_correlation ON agent_steps(correlation_id,id);
CREATE TRIGGER agent_steps_no_update BEFORE UPDATE ON agent_steps
BEGIN SELECT RAISE(ABORT,'Agent steps are append only'); END;
CREATE TRIGGER agent_steps_no_delete BEFORE DELETE ON agent_steps
BEGIN SELECT RAISE(ABORT,'Agent steps are append only'); END;

CREATE TABLE domain_generation (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL);
INSERT INTO domain_generation VALUES (1,0);
