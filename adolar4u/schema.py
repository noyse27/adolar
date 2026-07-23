"""Database schema owned by the optional Adolar4U module."""


def init_schema(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS adolar4u_user_settings (
            user_id               INTEGER PRIMARY KEY
                                  REFERENCES users(id) ON DELETE CASCADE,
            enabled               INTEGER NOT NULL DEFAULT 0,
            learning_paused       INTEGER NOT NULL DEFAULT 0,
            collaborative_enabled INTEGER NOT NULL DEFAULT 0,
            discovery_level       REAL NOT NULL DEFAULT 0.40,
            onboarding_completed_at REAL,
            updated_at            REAL NOT NULL DEFAULT (unixepoch()),
            CHECK(discovery_level >= 0.0 AND discovery_level <= 1.0)
        );

        CREATE TABLE IF NOT EXISTS adolar4u_recommendation_batches (
            id                   TEXT PRIMARY KEY,
            user_id              INTEGER NOT NULL
                                 REFERENCES users(id) ON DELETE CASCADE,
            shuffle_session_id   TEXT,
            algorithm_version    TEXT NOT NULL,
            requested_count      INTEGER NOT NULL,
            candidate_count      INTEGER NOT NULL,
            discovery_level      REAL NOT NULL,
            bucket_pool_json     TEXT NOT NULL DEFAULT '{}',
            bucket_target_json   TEXT NOT NULL DEFAULT '{}',
            bucket_selected_json TEXT NOT NULL DEFAULT '{}',
            profile_json         TEXT NOT NULL DEFAULT '{}',
            created_at           REAL NOT NULL DEFAULT (unixepoch())
        );

        CREATE TABLE IF NOT EXISTS adolar4u_recommendations (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id           TEXT NOT NULL
                               REFERENCES adolar4u_recommendation_batches(id)
                               ON DELETE CASCADE,
            user_id            INTEGER NOT NULL
                               REFERENCES users(id) ON DELETE CASCADE,
            track_id           INTEGER NOT NULL
                               REFERENCES tracks(id) ON DELETE CASCADE,
            queue_position     INTEGER NOT NULL,
            candidate_rank     INTEGER NOT NULL,
            bucket             TEXT NOT NULL,
            reason             TEXT NOT NULL,
            score              REAL NOT NULL,
            diagnostics_json   TEXT NOT NULL DEFAULT '{}',
            created_at         REAL NOT NULL DEFAULT (unixepoch()),
            CHECK(bucket IN ('anchor', 'similar', 'familiar', 'discovery'))
        );

        CREATE INDEX IF NOT EXISTS idx_a4u_batches_user_time
            ON adolar4u_recommendation_batches(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_a4u_recommendations_user_time
            ON adolar4u_recommendations(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_a4u_recommendations_user_track
            ON adolar4u_recommendations(user_id, track_id, created_at DESC);

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
            recommendation_id  INTEGER
                               REFERENCES adolar4u_recommendations(id)
                               ON DELETE SET NULL,
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

        CREATE TABLE IF NOT EXISTS adolar4u_seed_preferences (
            user_id      INTEGER NOT NULL
                         REFERENCES users(id) ON DELETE CASCADE,
            kind         TEXT NOT NULL CHECK(kind IN ('artist', 'genre')),
            value        TEXT NOT NULL,
            value_norm   TEXT NOT NULL,
            weight       REAL NOT NULL DEFAULT 1.0,
            created_at   REAL NOT NULL DEFAULT (unixepoch()),
            PRIMARY KEY (user_id, kind, value_norm)
        );
        CREATE INDEX IF NOT EXISTS idx_a4u_seed_user
            ON adolar4u_seed_preferences(user_id, kind);
    """)

    settings_columns = {
        row["name"] for row in conn.execute(
            "PRAGMA table_info(adolar4u_user_settings)"
        )
    }
    if "onboarding_completed_at" not in settings_columns:
        conn.execute("""
            ALTER TABLE adolar4u_user_settings
            ADD COLUMN onboarding_completed_at REAL
        """)

    event_columns = {
        row["name"] for row in conn.execute(
            "PRAGMA table_info(adolar4u_listening_events)"
        )
    }
    if "recommendation_id" not in event_columns:
        conn.execute("""
            ALTER TABLE adolar4u_listening_events
            ADD COLUMN recommendation_id INTEGER
            REFERENCES adolar4u_recommendations(id) ON DELETE SET NULL
        """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_a4u_events_recommendation
        ON adolar4u_listening_events(recommendation_id, event_type)
    """)
    conn.execute("""
        DELETE FROM adolar4u_recommendation_batches
        WHERE created_at < unixepoch() - 60 * 86400
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
