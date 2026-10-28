CREATE TABLE learned_rules (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('sender','preference')),
    status TEXT NOT NULL CHECK(status IN ('suggested','active','undone')),
    version INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('private','synthetic')),
    origin_type TEXT NOT NULL,
    origin_id TEXT,
    starts_after_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE TABLE learned_rule_versions (
    rule_id TEXT NOT NULL REFERENCES learned_rules(id),
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    PRIMARY KEY(rule_id,version)
);
CREATE TABLE learned_rule_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL REFERENCES learned_rules(id),
    version INTEGER NOT NULL,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    content_hash TEXT NOT NULL,
    used_at TEXT NOT NULL,
    UNIQUE(rule_id,version,message_id,content_hash)
);
CREATE TRIGGER domain_rules_insert AFTER INSERT ON learned_rules
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_rules_update AFTER UPDATE ON learned_rules
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_rule_versions_insert AFTER INSERT ON learned_rule_versions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_rule_uses_insert AFTER INSERT ON learned_rule_uses
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER rule_versions_no_update BEFORE UPDATE ON learned_rule_versions
BEGIN SELECT RAISE(ABORT,'Rule versions are append only'); END;
CREATE TRIGGER rule_versions_no_delete BEFORE DELETE ON learned_rule_versions
BEGIN SELECT RAISE(ABORT,'Rule versions are append only'); END;
