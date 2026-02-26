-- ai-trainer-gen script store schema
-- Applied automatically by ScriptStore on first open.

CREATE TABLE IF NOT EXISTS scripts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_hash     TEXT    NOT NULL,
    game_name     TEXT    NOT NULL DEFAULT '',
    engine_type   TEXT    NOT NULL DEFAULT '',
    feature       TEXT    NOT NULL,
    lua_script    TEXT    NOT NULL,
    aob_sigs      TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_used     TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_hash, feature)
);

CREATE INDEX IF NOT EXISTS idx_game_hash ON scripts(game_hash);
CREATE INDEX IF NOT EXISTS idx_game_name ON scripts(game_name);
