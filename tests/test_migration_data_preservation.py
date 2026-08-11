"""Regression test for a real data-loss bug found in production.

Renaming a table (as the control/content split migration and the
FK-stripping rebuild both do) makes SQLite auto-rewrite *other* tables'
REFERENCES clauses to point at the new (temporary) name. Dropping that
renamed table then immediately fires any ON DELETE CASCADE/SET NULL from
those other tables — silently wiping their rows before they get their own
turn to migrate. This lost real sessions, Last.fm loved tracks, and the
Adolar4U recommendation-to-listening-event link on an actual deployment.
The fix wraps the whole rename/drop migration section in
PRAGMA foreign_keys=OFF (db.py, in init_db()).
"""

import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-migpreserve-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-migpreserve-import-control.db"),
)

from adolar import db  # noqa: E402


class LegacyMigrationPreservesCrossReferencedDataTests(unittest.TestCase):
    """Builds a pre-split single-file database with real, linked history
    (mirroring years of actual usage, not an empty dev database) and
    asserts every row and every foreign key value survives db.init_db()."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "legacy.db")
        self.control_path = os.path.join(self.temp.name, "legacy-control.db")
        self._build_legacy_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def _build_legacy_fixture(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
                allow_download INTEGER NOT NULL DEFAULT 0, allow_playlists INTEGER NOT NULL DEFAULT 1,
                allow_radio_stations INTEGER NOT NULL DEFAULT 1, contributes_playcount INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'x', 'admin');

            CREATE TABLE sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL, connection_id INTEGER);
            INSERT INTO sessions (token, user_id, expires_at) VALUES ('realtoken123', 1, 99999999999);

            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);

            CREATE TABLE lastfm_loved_tracks (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                artist_norm TEXT NOT NULL, title_norm TEXT NOT NULL,
                artist TEXT, title TEXT, loved_at INTEGER, synced_at REAL,
                PRIMARY KEY (user_id, artist_norm, title_norm)
            );
            INSERT INTO lastfm_loved_tracks (user_id, artist_norm, title_norm, artist, title, loved_at, synced_at)
            VALUES (1, 'queen', 'bohemian rhapsody', 'Queen', 'Bohemian Rhapsody', 1700000000, 1700000001);

            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, title TEXT,
                artist TEXT, album TEXT, genre TEXT, year INTEGER, track_no INTEGER,
                duration INTEGER, bitrate INTEGER, size INTEGER, cover_hash TEXT, bpm REAL,
                mtime REAL, play_count INTEGER NOT NULL DEFAULT 0,
                play_count_tag_dirty INTEGER NOT NULL DEFAULT 0, loved INTEGER NOT NULL DEFAULT 0,
                indexed_at REAL DEFAULT (unixepoch())
            );
            INSERT INTO tracks (id, path, title, artist, album, genre, year)
            VALUES (501, '/music/a.mp3', 'A', 'Artist', 'Album', 'Rock', 2000);

            CREATE TABLE adolar4u_recommendation_batches (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                shuffle_session_id TEXT, algorithm_version TEXT NOT NULL, requested_count INTEGER NOT NULL,
                candidate_count INTEGER NOT NULL, discovery_level REAL NOT NULL,
                bucket_pool_json TEXT NOT NULL DEFAULT '{}', bucket_target_json TEXT NOT NULL DEFAULT '{}',
                bucket_selected_json TEXT NOT NULL DEFAULT '{}', profile_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT (unixepoch())
            );
            INSERT INTO adolar4u_recommendation_batches (id, user_id, algorithm_version, requested_count, candidate_count, discovery_level)
            VALUES ('batch1', 1, 'v1', 5, 20, 0.4);

            CREATE TABLE adolar4u_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL REFERENCES adolar4u_recommendation_batches(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                queue_position INTEGER NOT NULL, candidate_rank INTEGER NOT NULL, bucket TEXT NOT NULL,
                reason TEXT NOT NULL, score REAL NOT NULL, diagnostics_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT (unixepoch())
            );
            INSERT INTO adolar4u_recommendations (id, batch_id, user_id, track_id, queue_position, candidate_rank, bucket, reason, score)
            VALUES (1, 'batch1', 1, 501, 0, 0, 'anchor', 'because reasons', 0.9);

            CREATE TABLE adolar4u_user_settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL DEFAULT 0, learning_paused INTEGER NOT NULL DEFAULT 0,
                collaborative_enabled INTEGER NOT NULL DEFAULT 0, discovery_level REAL NOT NULL DEFAULT 0.40,
                onboarding_completed_at REAL, updated_at REAL NOT NULL DEFAULT (unixepoch())
            );
            INSERT INTO adolar4u_user_settings (user_id, enabled, discovery_level) VALUES (1, 1, 0.4);

            CREATE TABLE adolar4u_seed_preferences (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, value TEXT NOT NULL, value_norm TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0, created_at REAL NOT NULL DEFAULT (unixepoch()),
                PRIMARY KEY (user_id, kind, value_norm)
            );
            INSERT INTO adolar4u_seed_preferences (user_id, kind, value, value_norm) VALUES (1, 'artist', 'Queen', 'queen');

            CREATE TABLE adolar4u_listening_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL, position_seconds REAL NOT NULL DEFAULT 0, duration_seconds REAL NOT NULL DEFAULT 0,
                completion_ratio REAL NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'unknown', reason TEXT,
                session_id TEXT, client_event_id TEXT,
                recommendation_id INTEGER REFERENCES adolar4u_recommendations(id) ON DELETE SET NULL,
                created_at REAL NOT NULL DEFAULT (unixepoch())
            );
            INSERT INTO adolar4u_listening_events (user_id, track_id, event_type, client_event_id, recommendation_id)
            VALUES (1, 501, 'completed', 'evt-real-history-1', 1);
        """)
        conn.commit()
        conn.close()

    def test_sessions_lastfm_and_adolar4u_history_all_survive(self):
        with mock.patch.object(db, "DB_PATH", self.db_path), \
             mock.patch.object(db, "CONTROL_DB_PATH", self.control_path):
            db.init_db()

            with db.db() as conn:
                session = conn.execute("SELECT * FROM control.sessions").fetchone()
                self.assertIsNotNone(session, "session was lost during migration")
                self.assertEqual(session["token"], "realtoken123")
                self.assertEqual(session["user_id"], 1)

                loved = conn.execute("SELECT * FROM control.lastfm_loved_tracks").fetchone()
                self.assertIsNotNone(loved, "Last.fm loved track was lost during migration")
                self.assertEqual(loved["artist"], "Queen")

                recommendation = conn.execute("SELECT * FROM main.adolar4u_recommendations").fetchone()
                self.assertIsNotNone(recommendation, "Adolar4U recommendation was lost during migration")
                self.assertEqual(recommendation["track_id"], 501)

                event = conn.execute("SELECT * FROM main.adolar4u_listening_events").fetchone()
                self.assertIsNotNone(event)
                self.assertEqual(
                    event["recommendation_id"], 1,
                    "listening_events -> recommendations link was nulled during migration",
                )

                batch = conn.execute("SELECT * FROM main.adolar4u_recommendation_batches").fetchone()
                self.assertIsNotNone(batch, "Adolar4U recommendation batch was lost during migration")

                settings_row = conn.execute("SELECT * FROM main.adolar4u_user_settings").fetchone()
                self.assertIsNotNone(settings_row, "Adolar4U user settings were lost during migration")

                seed = conn.execute("SELECT * FROM main.adolar4u_seed_preferences").fetchone()
                self.assertIsNotNone(seed, "Adolar4U seed preferences were lost during migration")

    def test_migration_is_idempotent_and_keeps_data_on_second_run(self):
        with mock.patch.object(db, "DB_PATH", self.db_path), \
             mock.patch.object(db, "CONTROL_DB_PATH", self.control_path):
            db.init_db()
            db.init_db()
            with db.db() as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) c FROM control.sessions").fetchone()["c"], 1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) c FROM main.adolar4u_recommendations").fetchone()["c"], 1,
                )


if __name__ == "__main__":
    unittest.main()
