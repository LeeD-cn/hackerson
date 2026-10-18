-- v0.1 baseline: one project per backend instance; UTC ISO-8601 timestamps.
-- Task deletion is archival. Application services own authorization and DAG checks.
PRAGMA foreign_keys=ON;
PRAGMA user_version=1;
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '',
    private_context TEXT NOT NULL DEFAULT '', guidance TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', acceptance TEXT NOT NULL DEFAULT '',
    contract TEXT NOT NULL DEFAULT '', constraints TEXT NOT NULL DEFAULT '',
    parent_id TEXT REFERENCES tasks(task_id), executor TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','in_review','done','blocked')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status != 'done' OR progress=100), CHECK(parent_id IS NULL OR parent_id != task_id)
);
CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id), depends_on TEXT NOT NULL REFERENCES tasks(task_id),
    PRIMARY KEY(task_id, depends_on), CHECK(task_id != depends_on)
);
CREATE TABLE IF NOT EXISTS task_contexts (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    data TEXT NOT NULL CHECK(json_valid(data) AND json_type(data)='object'), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_history (
    task_id TEXT NOT NULL REFERENCES tasks(task_id), version INTEGER NOT NULL CHECK(version >= 1),
    data TEXT NOT NULL CHECK(json_valid(data) AND json_type(data)='object'),
    updated_at TEXT NOT NULL, PRIMARY KEY(task_id, version)
);
CREATE TABLE IF NOT EXISTS credentials (
    token_hash TEXT PRIMARY KEY CHECK(length(token_hash)=64),
    role TEXT NOT NULL CHECK(role IN ('task','coordinator','reviewer')), task_id TEXT REFERENCES tasks(task_id),
    created_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
    CHECK((role='task' AND task_id IS NOT NULL) OR (role IN ('coordinator','reviewer') AND task_id IS NULL))
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, sender TEXT NOT NULL, target TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('message','query','contract_response','status')),
    body TEXT NOT NULL, reply_to TEXT REFERENCES messages(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_requests (
    id TEXT PRIMARY KEY, proposer TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    title TEXT NOT NULL, rationale TEXT NOT NULL,
    patch TEXT NOT NULL CHECK(json_valid(patch) AND json_type(patch)='object'), base_version INTEGER NOT NULL CHECK(base_version >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    review_note TEXT NOT NULL DEFAULT '', reviewed_by TEXT,
    created_at TEXT NOT NULL, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY, project_version INTEGER NOT NULL UNIQUE CHECK(project_version >= 1),
    task_id TEXT REFERENCES tasks(task_id),
    title TEXT NOT NULL, body TEXT NOT NULL, actor TEXT NOT NULL,
    change_id TEXT REFERENCES change_requests(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id),
    task_id TEXT NOT NULL REFERENCES tasks(task_id), project_version INTEGER NOT NULL CHECK(project_version >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','acknowledged','completed')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, acknowledged_at TEXT, completed_at TEXT,
    UNIQUE(decision_id, task_id)
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
    commit_sha TEXT NOT NULL CHECK(length(commit_sha)=40), branch TEXT NOT NULL, summary TEXT NOT NULL,
    test_results TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','changes_requested','integrated')),
    feedback TEXT NOT NULL DEFAULT '', reviewer TEXT, integration_commit TEXT,
    integration_note TEXT, created_at TEXT NOT NULL, reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_task ON notifications(task_id);
CREATE INDEX IF NOT EXISTS idx_messages_target ON messages(target);
CREATE INDEX IF NOT EXISTS idx_dependencies_reverse ON task_dependencies(depends_on);
CREATE INDEX IF NOT EXISTS idx_submissions_task ON submissions(task_id);
