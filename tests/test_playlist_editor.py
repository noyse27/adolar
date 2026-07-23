import json
import os
import tempfile
import unittest
from unittest import mock

import app as app_module


class PlaylistEditorTests(unittest.TestCase):
    USER_ID = 71

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            app_module.db, "DB_PATH", os.path.join(self.temp.name, "playlist-editor.db")
        )
        self.db_patch.start()
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO users
                   (id, username, password_hash, role, allow_playlists, must_change_password)
                   VALUES (?, 'playlist-user', 'unused', 'user', 1, 0)""",
                (self.USER_ID,),
            )
            conn.executemany(
                """INSERT INTO tracks
                   (id, path, title, artist, album, genre, year, duration)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (701, "one.mp3", "One", "Alpha", "First", "Rock", 1991, 180),
                    (702, "two.mp3", "Two", "Beta", "Second", "Jazz", 2002, 200),
                ],
            )
        self.user = {
            "id": self.USER_ID,
            "username": "playlist-user",
            "role": "user",
            "allow_download": 0,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "playlist-editor-token")

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _login(self):
        return mock.patch.object(
            app_module._auth, "get_user_by_token", return_value=self.user
        )

    @staticmethod
    def _filter(field="genre", value="Rock"):
        return {
            "editor_version": 1,
            "search": {"title": "", "artist": "", "album": ""},
            "rules": {
                "mode": "all",
                "rules": [{"field": field, "op": "contains", "value": value}],
            },
        }

    def test_static_playlist_preserves_exact_tracks_and_order(self):
        playlist_id = app_module.db.save_personal_playlist(
            self.USER_ID, "Fest", "static", json.dumps(self._filter()),
            "artist", [702, 701],
        )
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO tracks (id, path, title, artist, genre)
                   VALUES (703, 'three.mp3', 'Three', 'Gamma', 'Rock')"""
            )
        tracks = app_module.db.get_playlist_tracks(playlist_id, self.USER_ID)
        self.assertEqual([track["id"] for track in tracks], [702, 701])

    def test_smart_playlist_runs_saved_filter_again(self):
        playlist_id = app_module.db.save_personal_playlist(
            self.USER_ID, "Lebendig", "smart", json.dumps(self._filter()),
            "artist", [701],
        )
        self.assertEqual(
            [track["id"] for track in app_module.db.get_playlist_tracks(
                playlist_id, self.USER_ID
            )],
            [701],
        )
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO tracks (id, path, title, artist, genre)
                   VALUES (703, 'three.mp3', 'Three', 'Gamma', 'Rock')"""
            )
        self.assertEqual(
            [track["id"] for track in app_module.db.get_playlist_tracks(
                playlist_id, self.USER_ID
            )],
            [701, 703],
        )

    def test_editor_api_saves_and_updates_playlist(self):
        with self._login():
            created = self.client.post("/api/playlists", json={
                "name": "Meine Auswahl",
                "type": "static",
                "filters": self._filter(),
                "track_ids": [701, 702],
            })
        self.assertEqual(created.status_code, 201)
        playlist_id = created.get_json()["id"]

        with self._login():
            updated = self.client.put(f"/api/playlists/{playlist_id}", json={
                "name": "Meine Smart-Auswahl",
                "type": "smart",
                "filters": self._filter("artist", "Beta"),
                "track_ids": [701],
            })
            tracks = self.client.get(f"/api/playlists/{playlist_id}/tracks")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual([track["id"] for track in tracks.get_json()], [702])

    def test_default_names_are_monotonic(self):
        app_module.db.save_personal_playlist(
            self.USER_ID, "Neue Playlist 4", "static", "{}", "artist", []
        )
        app_module.db.save_personal_playlist(
            self.USER_ID, "Urlaub", "static", "{}", "artist", []
        )
        self.assertEqual(app_module.db.next_playlist_name(self.USER_ID), "Neue Playlist 5")

    def test_web_ui_contains_editor_type_and_export_controls(self):
        page = (
            os.path.join(os.path.dirname(app_module.__file__), "templates", "index.html")
        )
        with open(page, encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn('id="btn-playlist-editor"', html)
        self.assertIn('id="btn-playlist-export"', html)
        self.assertIn('value="smart"', html)
        self.assertIn('value="static"', html)
        self.assertNotIn('id="analyze-bpm"', html)


if __name__ == "__main__":
    unittest.main()
