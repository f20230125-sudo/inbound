CREATE TABLE evidence_projects (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, stack_json TEXT NOT NULL,
    live_url TEXT, code_url TEXT, source_file TEXT, source_hash TEXT, as_of TEXT,
    scope TEXT NOT NULL CHECK(scope IN ('public','demo')), facts_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE evidence_bullets (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES evidence_projects(id),
    text_tex TEXT NOT NULL, text_plain TEXT NOT NULL, source_file TEXT NOT NULL,
    source_line INTEGER NOT NULL, source_hash TEXT NOT NULL, preferred INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, ordinal INTEGER NOT NULL
);
CREATE TABLE skills (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases_json TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('public','demo')), category TEXT NOT NULL,
    approved INTEGER NOT NULL, facts_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE skill_evidence (
    skill_id TEXT NOT NULL REFERENCES skills(id),
    project_id TEXT NOT NULL REFERENCES evidence_projects(id), note TEXT NOT NULL,
    approved INTEGER NOT NULL, PRIMARY KEY(skill_id,project_id)
);
CREATE TABLE evidence_snapshots (scope TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
CREATE TABLE packs (
    id TEXT PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id),
    role_id INTEGER REFERENCES roles(id), revision_id INTEGER REFERENCES opportunity_revisions(id),
    status TEXT NOT NULL CHECK(status IN
        ('new','preparing','needs_review','reviewed','submitted_by_me','blocked','skipped')),
    selection_json TEXT NOT NULL DEFAULT '{}', files_json TEXT NOT NULL DEFAULT '{}',
    checks_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
    provisional INTEGER NOT NULL DEFAULT 0, blocker_acknowledged INTEGER NOT NULL DEFAULT 0,
    demo INTEGER NOT NULL DEFAULT 0
);
