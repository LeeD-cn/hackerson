-- Additive web-planning storage; does not change existing v0.1 task tables.
CREATE TABLE IF NOT EXISTS planning_drafts (
    draft_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','applied')),
    base_project_version INTEGER NOT NULL,
    base_fingerprint TEXT NOT NULL,
    plan TEXT NOT NULL CHECK(json_valid(plan)),
    messages TEXT NOT NULL CHECK(json_valid(messages)),
    applied_result TEXT CHECK(applied_result IS NULL OR json_valid(applied_result)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
