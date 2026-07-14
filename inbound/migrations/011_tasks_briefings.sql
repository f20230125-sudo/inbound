CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    course TEXT,
    title TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('synthetic','private')),
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','done','snoozed','not_mine')),
    snoozed_until TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE task_revisions (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    message_id INTEGER NOT NULL REFERENCES messages(id),
    content_hash TEXT NOT NULL,
    course TEXT,
    title TEXT NOT NULL,
    deadline_json TEXT NOT NULL,
    source_quote TEXT NOT NULL,
    amendment INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(message_id,content_hash)
);
CREATE TABLE task_actions (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    action TEXT NOT NULL CHECK(action IN ('done','snooze','not_mine','undo')),
    previous_state TEXT NOT NULL,
    previous_until TEXT,
    undone_action_id INTEGER REFERENCES task_actions(id),
    created_at TEXT NOT NULL
);
CREATE TABLE briefings (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    generation INTEGER NOT NULL,
    projection_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('synthetic','private')),
    payload_json TEXT NOT NULL,
    UNIQUE(day,projection_key)
);
CREATE TRIGGER domain_tasks_insert AFTER INSERT ON tasks
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_tasks_update AFTER UPDATE ON tasks
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_tasks_delete AFTER DELETE ON tasks
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_task_revisions_insert AFTER INSERT ON task_revisions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER domain_task_actions_insert AFTER INSERT ON task_actions
BEGIN UPDATE domain_generation SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER task_revisions_no_update BEFORE UPDATE ON task_revisions
BEGIN SELECT RAISE(ABORT,'Task source history is append only'); END;
CREATE TRIGGER task_revisions_no_delete BEFORE DELETE ON task_revisions
BEGIN SELECT RAISE(ABORT,'Task source history is append only'); END;
CREATE TRIGGER task_actions_no_update BEFORE UPDATE ON task_actions
BEGIN SELECT RAISE(ABORT,'Task actions are append only'); END;
CREATE TRIGGER task_actions_no_delete BEFORE DELETE ON task_actions
BEGIN SELECT RAISE(ABORT,'Task actions are append only'); END;
CREATE TRIGGER briefings_no_update BEFORE UPDATE ON briefings
BEGIN SELECT RAISE(ABORT,'Briefings are append only'); END;
CREATE TRIGGER briefings_no_delete BEFORE DELETE ON briefings
BEGIN SELECT RAISE(ABORT,'Briefings are append only'); END;
