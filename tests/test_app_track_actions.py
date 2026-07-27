import os
import tempfile
import unittest
from unittest import mock

from mutagen.id3 import ID3, PCNT

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-trackactions-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-trackactions-import-control.db"),
)

import app as app_module


def _make_mp3(path: str) -> None:
    header = bytes([0xFF, 0xFB, 0x90, 0xC4])
    frame_size = 144 * 128000 // 44100
    frame = header + bytes(frame_size - len(header))
    with open(path, "wb") as f:
        for _ in range(10):
            f.write(frame)


class TrackActionsTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music_root = os.path.join(self.temp.name, "music")
        os.makedirs(self.music_root)
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
            mock.patch.object(app_module, "MUSIC_ROOT", self.music_root),
            mock.patch.object(
                app_module, "LIBRARY_REGISTRY_PATH",
                os.path.join(self.temp.name, "libraries.json"),
            ),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        self.client = app_module.app.test_client()
        with app_module.db.db() as conn:
            self.track_id = conn.execute(
                "INSERT INTO tracks (path, title, bpm) VALUES ('a.mp3', 'A', NULL)",
            ).lastrowid

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _login(self, **overrides):
        user = {
            "id": 1, "username": "u", "role": "user", "allow_download": 0,
            "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
            "is_active": 1, "must_change_password": 0,
        }
        user.update(overrides)
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user)


class TrackBpmRouteTests(TrackActionsTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.post(f"/api/track/{self.track_id}/bpm", json={"bpm": 128})
        self.assertEqual(response.status_code, 403)

    def test_rejects_missing_bpm(self):
        with self._login(role="admin"):
            response = self.client.post(f"/api/track/{self.track_id}/bpm", json={})
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_positive_bpm(self):
        with self._login(role="admin"):
            response = self.client.post(f"/api/track/{self.track_id}/bpm", json={"bpm": 0})
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_numeric_bpm(self):
        with self._login(role="admin"):
            response = self.client.post(f"/api/track/{self.track_id}/bpm", json={"bpm": "fast"})
        self.assertEqual(response.status_code, 400)

    def test_valid_bpm_updates_the_track(self):
        with self._login(role="admin"):
            response = self.client.post(f"/api/track/{self.track_id}/bpm", json={"bpm": 128.456})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["updated"])
        with app_module.db.db() as conn:
            bpm = conn.execute("SELECT bpm FROM tracks WHERE id=?", (self.track_id,)).fetchone()["bpm"]
        self.assertEqual(bpm, 128.46)


class TrackPlayedRouteTests(TrackActionsTestBase):
    def test_requires_authentication(self):
        response = self.client.post(f"/api/track/{self.track_id}/played")
        self.assertEqual(response.status_code, 401)

    def test_missing_track_returns_404(self):
        with self._login():
            response = self.client.post("/api/track/999999/played")
        self.assertEqual(response.status_code, 404)

    def test_non_contributing_user_play_count_is_hidden_in_response(self):
        with self._login(contributes_playcount=0):
            response = self.client.post(f"/api/track/{self.track_id}/played")
        data = response.get_json()
        self.assertFalse(data["contributed"])
        self.assertIsNone(data["play_count"])

    def test_contributing_user_play_count_is_reported(self):
        with self._login(contributes_playcount=1):
            response = self.client.post(f"/api/track/{self.track_id}/played")
        data = response.get_json()
        self.assertTrue(data["contributed"])
        self.assertEqual(data["play_count"], 1)


class TrackDiscoPlayedRouteTests(TrackActionsTestBase):
    def test_does_not_require_authentication(self):
        response = self.client.post(f"/api/track/{self.track_id}/disco-played")
        self.assertEqual(response.status_code, 200)

    def test_missing_track_returns_404(self):
        response = self.client.post("/api/track/999999/disco-played")
        self.assertEqual(response.status_code, 404)

    def test_increments_the_disco_user_play_count(self):
        self.client.post(f"/api/track/{self.track_id}/disco-played")
        self.client.post(f"/api/track/{self.track_id}/disco-played")
        with app_module.db.db() as conn:
            count = conn.execute(
                "SELECT count FROM user_play_counts WHERE user_id=0 AND track_id=?", (self.track_id,),
            ).fetchone()["count"]
        self.assertEqual(count, 2)


class PlayCountTagsStatusRouteTests(TrackActionsTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.get("/api/playcount-tags/status")
        self.assertEqual(response.status_code, 403)

    def test_reports_pending_count_and_sync_state(self):
        app_module.db.record_user_play(1, self.track_id, contributes=True)
        with self._login(role="admin"):
            response = self.client.get("/api/playcount-tags/status")
        data = response.get_json()
        self.assertEqual(data["pending"], 1)
        self.assertIn("running", data)
        self.assertIn("written", data)


class PlayCountTagsSyncRouteTests(TrackActionsTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.post("/api/playcount-tags/sync")
        self.assertEqual(response.status_code, 403)

    def test_starts_the_background_flush(self):
        with self._login(role="admin"), mock.patch.object(app_module, "_flush_play_count_tags"):
            response = self.client.post("/api/playcount-tags/sync")
        self.assertEqual(response.status_code, 200)

    def test_returns_409_when_already_running(self):
        app_module._play_count_tag_sync["running"] = True
        try:
            with self._login(role="admin"):
                response = self.client.post("/api/playcount-tags/sync")
            self.assertEqual(response.status_code, 409)
        finally:
            app_module._play_count_tag_sync["running"] = False


class FlushPlayCountTagsTests(TrackActionsTestBase):
    def test_a_fresh_mp3_with_no_existing_id3_tag_still_gets_written(self):
        # _write_play_count_tag's MP3 branch used to call ID3(path) directly
        # and let the exception bubble into the broad except-log-False
        # fallback whenever the file had no ID3 header yet. Fixed to fall
        # back to a fresh ID3(), matching scanner.py's _write_bpm_tag.
        path = os.path.join(self.music_root, "untagged.mp3")
        _make_mp3(path)  # no ID3 header at all
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (path, title, play_count, play_count_tag_dirty) "
                "VALUES ('untagged.mp3', 'Untagged', 5, 1)",
            )

        app_module._flush_play_count_tags()

        self.assertEqual(app_module._play_count_tag_sync["written"], 1)
        self.assertEqual(app_module.db.get_dirty_play_count_tags(), [])
        self.assertEqual(ID3(path)["PCNT"].count, 5)

    def test_writes_the_tag_and_marks_the_track_clean(self):
        path = os.path.join(self.music_root, "song.mp3")
        _make_mp3(path)
        with app_module.db.db() as conn:
            track_id = conn.execute(
                "INSERT INTO tracks (path, title, play_count, play_count_tag_dirty) "
                "VALUES ('song.mp3', 'Song', 5, 1)",
            ).lastrowid

        app_module._flush_play_count_tags()

        self.assertEqual(app_module._play_count_tag_sync["written"], 1)
        self.assertEqual(app_module.db.get_dirty_play_count_tags(), [])
        tags = ID3(path)
        self.assertEqual(tags["PCNT"].count, 5)
        with app_module.db.db() as conn:
            stored = conn.execute(
                "SELECT play_count FROM tracks WHERE id=?", (track_id,),
            ).fetchone()["play_count"]
        self.assertEqual(stored, 5)

    def test_keeps_the_higher_of_db_and_existing_file_tag_count(self):
        path = os.path.join(self.music_root, "song.mp3")
        _make_mp3(path)
        tags = ID3()
        tags["PCNT"] = PCNT(count=20)
        tags.save(path)
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (path, title, play_count, play_count_tag_dirty) "
                "VALUES ('song.mp3', 'Song', 3, 1)",
            )

        app_module._flush_play_count_tags()

        with app_module.db.db() as conn:
            stored = conn.execute("SELECT play_count FROM tracks WHERE path='song.mp3'").fetchone()[0]
        self.assertEqual(stored, 20)

    def test_missing_file_counts_as_failed_and_stays_dirty(self):
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (path, title, play_count, play_count_tag_dirty) "
                "VALUES ('gone.mp3', 'Gone', 1, 1)",
            )

        app_module._flush_play_count_tags()

        self.assertEqual(app_module._play_count_tag_sync["failed"], 1)
        self.assertEqual(len(app_module.db.get_dirty_play_count_tags()), 1)

    def test_is_a_no_op_when_already_running(self):
        app_module._play_count_tag_sync["running"] = True
        try:
            with app_module.db.db() as conn:
                conn.execute(
                    "INSERT INTO tracks (path, title, play_count, play_count_tag_dirty) "
                    "VALUES ('song.mp3', 'Song', 1, 1)",
                )
            app_module._flush_play_count_tags()
            # Guard clause returns immediately; nothing gets processed.
            self.assertEqual(len(app_module.db.get_dirty_play_count_tags()), 1)
        finally:
            app_module._play_count_tag_sync["running"] = False


if __name__ == "__main__":
    unittest.main()
