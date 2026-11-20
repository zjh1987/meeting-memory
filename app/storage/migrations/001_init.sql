CREATE TABLE IF NOT EXISTS project (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meeting (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uid            TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    project_id     INTEGER NOT NULL REFERENCES project(id),
    template_key   TEXT NOT NULL DEFAULT 'standard',
    recorded_at    TEXT NOT NULL,
    duration_sec   INTEGER NOT NULL DEFAULT 0,
    audio_filename TEXT NOT NULL,
    audio_size     INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',
    error_code     TEXT,
    error_msg      TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TEXT,
    transcript     TEXT,
    minutes        TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    heartbeat_at   TEXT
);

CREATE TABLE IF NOT EXISTS action_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id  INTEGER NOT NULL REFERENCES meeting(id),
    owner       TEXT,
    task        TEXT NOT NULL,
    due         TEXT,
    quote       TEXT NOT NULL,
    segment_ids TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id),
    target_id  INTEGER NOT NULL REFERENCES meeting(id),
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL,
    quote      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meeting_project  ON meeting(project_id);
CREATE INDEX IF NOT EXISTS idx_meeting_status   ON meeting(status);
CREATE INDEX IF NOT EXISTS idx_meeting_recorded ON meeting(recorded_at);
CREATE INDEX IF NOT EXISTS idx_action_meeting   ON action_item(meeting_id);
CREATE INDEX IF NOT EXISTS idx_action_status    ON action_item(status);
CREATE INDEX IF NOT EXISTS idx_relation_meeting ON relation(meeting_id);

INSERT OR IGNORE INTO project (name, created_at)
VALUES ('未归类', datetime('now', 'localtime'));
