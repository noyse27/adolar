"""Database schema owned by the optional Adolar4U module."""


def init_schema(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS adolar4u_user_settings (
            user_id               INTEGER PRIMARY KEY
                                  REFERENCES users(id) ON DELETE CASCADE,
            enabled               INTEGER NOT NULL DEFAULT 0,
            learning_paused       INTEGER NOT NULL DEFAULT 0,
            collaborative_enabled INTEGER NOT NULL DEFAULT 0,
            discovery_level       REAL NOT NULL DEFAULT 0.15,
            updated_at            REAL NOT NULL DEFAULT (unixepoch()),
            CHECK(discovery_level >= 0.0 AND discovery_level <= 1.0)
        );

        CREATE TABLE IF NOT EXISTS adolar4u_listening_events (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id            INTEGER NOT NULL
                               REFERENCES users(id) ON DELETE CASCADE,
            track_id           INTEGER NOT NULL
                               REFERENCES tracks(id) ON DELETE CASCADE,
            event_type         TEXT NOT NULL,
            position_seconds   REAL NOT NULL DEFAULT 0,
            duration_seconds   REAL NOT NULL DEFAULT 0,
            completion_ratio   REAL NOT NULL DEFAULT 0,
            source             TEXT NOT NULL DEFAULT 'unknown',
            reason             TEXT,
            session_id         TEXT,
            client_event_id    TEXT,
            created_at         REAL NOT NULL DEFAULT (unixepoch()),
            CHECK(event_type IN ('started', 'skipped', 'completed')),
            CHECK(position_seconds >= 0),
            CHECK(duration_seconds >= 0),
            CHECK(completion_ratio >= 0.0 AND completion_ratio <= 1.0),
            UNIQUE(user_id, client_event_id)
        );

        CREATE INDEX IF NOT EXISTS idx_a4u_events_user_time
            ON adolar4u_listening_events(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_a4u_events_user_track
            ON adolar4u_listening_events(user_id, track_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_a4u_events_track_type
            ON adolar4u_listening_events(track_id, event_type);
    """)

    defaults = {
        "adolar4u_enabled": "0",
        "adolar4u_audio_analysis": "0",
        "adolar4u_collaborative": "0",
    }
    conn.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        defaults.items(),
    )
