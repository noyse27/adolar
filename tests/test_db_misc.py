import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-misc-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-misc-import-control.db"),
)

import db


class MiscTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        with db.db() as conn:
            conn.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'u1', 'x')")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()


class GenresAndStatsTests(MiscTestBase):
    def test_get_genres_returns_distinct_sorted_non_empty_genres(self):
        with db.db() as conn:
            conn.executemany(
                "INSERT INTO tracks (path, genre) VALUES (?, ?)",
                [("/a.mp3", "Rock"), ("/b.mp3", "Jazz"), ("/c.mp3", "Rock"), ("/d.mp3", ""), ("/e.mp3", None)],
            )
        self.assertEqual(db.get_genres(), ["Jazz", "Rock"])

    def test_get_stats_reports_track_count_and_total_size_in_gb(self):
        with db.db() as conn:
            conn.execute("INSERT INTO tracks (path, size) VALUES ('/a.mp3', ?)", (1_073_741_824,))
            conn.execute("INSERT INTO tracks (path, size) VALUES ('/b.mp3', ?)", (536_870_912,))
        stats = db.get_stats()
        self.assertEqual(stats["total_tracks"], 2)
        self.assertEqual(stats["total_size_gb"], 1.5)

    def test_get_stats_on_empty_library(self):
        self.assertEqual(db.get_stats(), {"total_tracks": 0, "total_size_gb": 0})


class CoverTests(MiscTestBase):
    def test_save_cover_then_get_cover_round_trips(self):
        db.save_cover("hash123", b"binarydata", "image/png")
        data, mime = db.get_cover("hash123")
        self.assertEqual(data, b"binarydata")
        self.assertEqual(mime, "image/png")

    def test_save_cover_defaults_mime_to_jpeg(self):
        db.save_cover("hash456", b"data")
        _, mime = db.get_cover("hash456")
        self.assertEqual(mime, "image/jpeg")

    def test_save_cover_ignores_duplicate_hash(self):
        db.save_cover("dup", b"first", "image/png")
        db.save_cover("dup", b"second", "image/gif")
        data, mime = db.get_cover("dup")
        self.assertEqual(data, b"first")
        self.assertEqual(mime, "image/png")

    def test_get_cover_missing_hash_returns_none_none(self):
        self.assertEqual(db.get_cover("no-such-hash"), (None, None))


class UpdateBpmAndScannerStatusTests(MiscTestBase):
    def setUp(self):
        super().setUp()
        with db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path, bpm) VALUES ('/a.mp3', NULL)")
            self.track_id = cur.lastrowid

    def test_update_bpm_sets_value_when_previously_unset(self):
        self.assertTrue(db.update_bpm(self.track_id, 128.0))
        with db.db() as conn:
            row = conn.execute("SELECT bpm FROM tracks WHERE id=?", (self.track_id,)).fetchone()
        self.assertEqual(row["bpm"], 128.0)

    def test_update_bpm_does_not_overwrite_an_existing_value(self):
        db.update_bpm(self.track_id, 100.0)
        self.assertFalse(db.update_bpm(self.track_id, 140.0))
        with db.db() as conn:
            row = conn.execute("SELECT bpm FROM tracks WHERE id=?", (self.track_id,)).fetchone()
        self.assertEqual(row["bpm"], 100.0)

    def test_get_scanner_status_reports_track_count(self):
        self.assertEqual(
            db.get_scanner_status(),
            {"total_tracks": 1, "finished_at": None},
        )

    def test_last_scan_time_survives_database_reinitialization(self):
        db.set_last_scan_finished_at(1_722_085_200.5)

        db.init_db()

        self.assertEqual(db.get_scanner_status()["finished_at"], 1_722_085_200.5)


class IncrementUserPlayCountTests(MiscTestBase):
    def test_creates_then_increments_a_per_user_count(self):
        with db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path) VALUES ('/a.mp3')")
            track_id = cur.lastrowid
        db.increment_user_play_count(user_id=0, track_id=track_id)  # 0 = Disco
        db.increment_user_play_count(user_id=0, track_id=track_id)
        with db.db() as conn:
            row = conn.execute(
                "SELECT count FROM user_play_counts WHERE user_id=0 AND track_id=?", (track_id,),
            ).fetchone()
        self.assertEqual(row["count"], 2)


class LastfmAccountTests(MiscTestBase):
    def test_get_lastfm_account_returns_none_when_not_connected(self):
        self.assertIsNone(db.get_lastfm_account(1))

    def test_set_then_get_lastfm_account_round_trips(self):
        db.set_lastfm_account(1, "myuser", "sesskey")
        account = db.get_lastfm_account(1)
        self.assertEqual(account["username"], "myuser")
        self.assertEqual(account["session_key"], "sesskey")

    def test_reconnecting_updates_username_and_session_key(self):
        db.set_lastfm_account(1, "old", "old-key")
        db.set_lastfm_account(1, "new", "new-key")
        account = db.get_lastfm_account(1)
        self.assertEqual(account["username"], "new")
        self.assertEqual(account["session_key"], "new-key")

    def test_disconnect_removes_account_and_related_rows(self):
        db.set_lastfm_account(1, "user", "key")
        db.replace_lastfm_loved_tracks(1, [{"artist": "A", "title": "B"}])
        db.get_lastfm_sync_state(1, "loved")

        db.disconnect_lastfm_account(1)

        self.assertIsNone(db.get_lastfm_account(1))
        self.assertEqual(db.get_lastfm_loved_status(1)["total"], 0)

    def test_set_auto_love_returns_false_for_unconnected_account(self):
        self.assertFalse(db.set_lastfm_auto_love(1, True))

    def test_set_auto_love_updates_connected_account(self):
        db.set_lastfm_account(1, "user", "key")
        self.assertTrue(db.set_lastfm_auto_love(1, False))


class LastfmSyncStateTests(MiscTestBase):
    def test_rejects_invalid_job_type(self):
        with self.assertRaises(ValueError):
            db.get_lastfm_sync_state(1, "not-a-real-job")
        with self.assertRaises(ValueError):
            db.claim_lastfm_sync_job(1, "not-a-real-job")
        with self.assertRaises(ValueError):
            db.update_lastfm_sync_state(1, "bogus", running=True)

    def test_update_lastfm_sync_state_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            db.update_lastfm_sync_state(1, "loved", not_a_real_field=1)

    def test_loved_job_state_uses_count_key_not_updated(self):
        state = db.get_lastfm_sync_state(1, "loved")
        self.assertIn("count", state)
        self.assertNotIn("updated", state)

    def test_playcounts_job_state_uses_updated_key_not_count(self):
        state = db.get_lastfm_sync_state(1, "playcounts")
        self.assertIn("updated", state)
        self.assertNotIn("count", state)

    def test_claim_lastfm_sync_job_only_succeeds_when_not_already_running(self):
        self.assertTrue(db.claim_lastfm_sync_job(1, "loved"))
        self.assertFalse(db.claim_lastfm_sync_job(1, "loved"))

    def test_update_lastfm_sync_state_persists_values(self):
        db.claim_lastfm_sync_job(1, "loved")
        state = db.update_lastfm_sync_state(1, "loved", done=5, total=10, result_count=5)
        self.assertEqual(state["done"], 5)
        self.assertEqual(state["total"], 10)
        self.assertEqual(state["count"], 5)


class ReplaceLastfmLovedTracksTests(MiscTestBase):
    def test_replace_stores_normalized_entries_and_returns_count(self):
        db.set_lastfm_account(1, "user", "key")  # loved_synced_at only updates a connected account
        count = db.replace_lastfm_loved_tracks(1, [
            {"artist": "Daft Punk", "title": "Get Lucky", "loved_at": 123},
            {"artist": "", "title": "Skipped (no artist)"},
        ])
        self.assertEqual(count, 1)
        status = db.get_lastfm_loved_status(1)
        self.assertEqual(status["total"], 1)
        self.assertIsNotNone(status["synced_at"])

    def test_replace_clears_previous_entries(self):
        db.replace_lastfm_loved_tracks(1, [{"artist": "A", "title": "One"}])
        db.replace_lastfm_loved_tracks(1, [{"artist": "B", "title": "Two"}])
        self.assertEqual(db.get_lastfm_loved_status(1)["total"], 1)


class SetLastfmLovedTests(MiscTestBase):
    def test_loving_a_track_adds_it(self):
        db.set_lastfm_loved(1, "Artist", "Title", True)
        self.assertEqual(db.get_lastfm_loved_status(1)["total"], 1)

    def test_unloving_removes_it(self):
        db.set_lastfm_loved(1, "Artist", "Title", True)
        db.set_lastfm_loved(1, "Artist", "Title", False)
        self.assertEqual(db.get_lastfm_loved_status(1)["total"], 0)

    def test_blank_artist_or_title_is_a_no_op(self):
        db.set_lastfm_loved(1, "", "Title", True)
        self.assertEqual(db.get_lastfm_loved_status(1)["total"], 0)


if __name__ == "__main__":
    unittest.main()
