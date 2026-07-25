import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-favplaylists-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-favplaylists-import-control.db"),
)

import app as app_module
import db


class FavoritesPlaylistsTestBase(unittest.TestCase):
    USER_ID = 1
    OTHER_USER_ID = 2

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO users (id, username, password_hash, role, allow_playlists, must_change_password)
                   VALUES (?, 'user1', 'x', 'user', 1, 0)""", (self.USER_ID,),
            )
            conn.execute(
                """INSERT INTO users (id, username, password_hash, role, allow_playlists, must_change_password)
                   VALUES (?, 'user2', 'x', 'user', 1, 0)""", (self.OTHER_USER_ID,),
            )
            conn.execute(
                "INSERT INTO tracks (id, path, title, artist) VALUES (901, '/a.mp3', 'A', 'Artist')",
            )
        self.user = {
            "id": self.USER_ID, "username": "user1", "role": "user",
            "allow_download": 0, "allow_playlists": 1, "allow_radio_stations": 1,
            "contributes_playcount": 0, "is_active": 1, "must_change_password": 0,
        }
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "fav-playlist-token")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _login(self, allow_playlists=1):
        user = dict(self.user, allow_playlists=allow_playlists)
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user), mock.patch.object(
            app_module.db, "get_setting", return_value="1",
        )


class FavoritesRouteTests(FavoritesPlaylistsTestBase):
    def test_status_reports_no_favorites_initially(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.get("/api/favorites?ids=901")
        self.assertEqual(response.get_json()["track_ids"], [])

    def test_set_favorite_true_then_status_reflects_it(self):
        login, setting = self._login()
        with login, setting:
            put_response = self.client.put("/api/favorites/901", json={"favorite": True})
            self.assertEqual(put_response.status_code, 200)
            status = self.client.get("/api/favorites?ids=901")
        self.assertEqual(status.get_json()["track_ids"], [901])

    def test_set_favorite_requires_boolean_field(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.put("/api/favorites/901", json={"favorite": "yes"})
        self.assertEqual(response.status_code, 400)

    def test_set_favorite_for_missing_track_returns_404(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.put("/api/favorites/999999", json={"favorite": True})
        self.assertEqual(response.status_code, 404)


class BookmarkRouteTests(FavoritesPlaylistsTestBase):
    def test_requires_authentication(self):
        response = self.client.post("/api/radio/bookmark/901")
        self.assertEqual(response.status_code, 401)

    def test_bookmarking_adds_to_favorites_and_returns_playlist_id(self):
        with mock.patch.object(app_module._auth, "get_user_by_token", return_value=self.user):
            response = self.client.post("/api/radio/bookmark/901")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["favorite"])
        self.assertIn("playlist_id", data)
        self.assertEqual(db.get_favorite_track_ids(self.USER_ID), {901})


class PlaylistMembershipsRouteTests(FavoritesPlaylistsTestBase):
    def test_truly_anonymous_request_is_blocked_by_auth_middleware(self):
        # This path isn't in before_request's anonymous-view allowlist (unlike
        # "/api/playlists" and "*/tracks"), so it 401s before the route's own
        # "no g.user" check is ever reached.
        response = self.client.get("/api/playlists/memberships?ids=901")
        self.assertEqual(response.status_code, 401)

    def test_logged_in_user_without_playlist_capability_gets_empty_object(self):
        login, setting = self._login(allow_playlists=0)
        with login, setting:
            response = self.client.get("/api/playlists/memberships?ids=901")
        self.assertEqual(response.get_json(), {})

    def test_reports_which_playlists_contain_the_track(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mix", "static", "{}", "artist", [901])
        login, setting = self._login()
        with login, setting:
            response = self.client.get("/api/playlists/memberships?ids=901")
        self.assertEqual(response.get_json(), {"901": [playlist_id]})

    def test_invalid_ids_param_returns_400(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.get("/api/playlists/memberships?ids=abc")
        # non-digit tokens are silently filtered, not a hard error -> empty result
        self.assertEqual(response.status_code, 200)


class PlaylistAddTrackRouteTests(FavoritesPlaylistsTestBase):
    def test_requires_create_playlists_capability(self):
        login, _ = self._login(allow_playlists=0)
        with login, mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.post("/api/playlists/1/tracks", json={"track_id": 901})
        self.assertEqual(response.status_code, 403)

    def test_requires_track_id(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mix", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.post(f"/api/playlists/{playlist_id}/tracks", json={})
        self.assertEqual(response.status_code, 400)

    def test_unknown_playlist_returns_404(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post("/api/playlists/999999/tracks", json={"track_id": 901})
        self.assertEqual(response.status_code, 404)

    def test_cannot_add_to_a_smart_playlist(self):
        playlist_id = db.create_playlist(self.USER_ID, "Smart", "{}", "artist", type_="smart")
        login, setting = self._login()
        with login, setting:
            response = self.client.post(f"/api/playlists/{playlist_id}/tracks", json={"track_id": 901})
        self.assertEqual(response.status_code, 409)

    def test_adds_track_to_a_static_playlist(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mix", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.post(f"/api/playlists/{playlist_id}/tracks", json={"track_id": 901})
        self.assertEqual(response.status_code, 200)
        tracks = db.get_playlist_tracks(playlist_id, self.USER_ID)
        self.assertEqual([t["id"] for t in tracks], [901])


class PlaylistTracksRouteTests(FavoritesPlaylistsTestBase):
    def test_unknown_playlist_returns_404(self):
        # Anonymous GET .../tracks is allowed through middleware only when
        # anonymous web viewing is enabled.
        with mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.get("/api/playlists/999999/tracks")
        self.assertEqual(response.status_code, 404)

    def test_owner_can_read_their_playlist_tracks(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mix", "static", "{}", "artist", [901])
        with mock.patch.object(app_module._auth, "get_user_by_token", return_value=self.user):
            response = self.client.get(f"/api/playlists/{playlist_id}/tracks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.get_json()], [901])


class PlaylistsListRouteTests(FavoritesPlaylistsTestBase):
    def test_anonymous_sees_system_playlists_when_anonymous_web_is_enabled(self):
        with mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.get("/api/playlists")
        self.assertEqual(response.status_code, 200)
        names = {p["name"] for p in response.get_json()}
        self.assertIn("Meistgespielt", names)

    def test_anonymous_is_blocked_when_anonymous_web_is_disabled(self):
        with mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.get("/api/playlists")
        self.assertEqual(response.status_code, 401)


class PlaylistsCrudPermissionTests(FavoritesPlaylistsTestBase):
    def test_create_requires_capability(self):
        login, _ = self._login(allow_playlists=0)
        with login, mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.post("/api/playlists", json={"name": "X"})
        self.assertEqual(response.status_code, 403)

    def test_create_requires_a_name(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post("/api/playlists", json={"name": "  "})
        self.assertEqual(response.status_code, 400)

    def test_update_missing_playlist_returns_404(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.put("/api/playlists/999999", json={"name": "New"})
        self.assertEqual(response.status_code, 404)

    def test_delete_requires_capability(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mine", "static", "{}", "artist", [])
        login, _ = self._login(allow_playlists=0)
        with login, mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.delete(f"/api/playlists/{playlist_id}")
        self.assertEqual(response.status_code, 403)

    def test_delete_someone_elses_playlist_returns_404(self):
        playlist_id = db.save_personal_playlist(self.OTHER_USER_ID, "Theirs", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.delete(f"/api/playlists/{playlist_id}")
        self.assertEqual(response.status_code, 404)

    def test_owner_can_delete_their_playlist(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mine", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.delete(f"/api/playlists/{playlist_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.get_personal_playlist(playlist_id, self.USER_ID))

    def test_rename_requires_a_name(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Mine", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.patch(f"/api/playlists/{playlist_id}", json={"name": ""})
        self.assertEqual(response.status_code, 400)

    def test_rename_someone_elses_playlist_returns_404(self):
        playlist_id = db.save_personal_playlist(self.OTHER_USER_ID, "Theirs", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.patch(f"/api/playlists/{playlist_id}", json={"name": "Hacked"})
        self.assertEqual(response.status_code, 404)

    def test_owner_can_rename_their_playlist(self):
        playlist_id = db.save_personal_playlist(self.USER_ID, "Old", "static", "{}", "artist", [])
        login, setting = self._login()
        with login, setting:
            response = self.client.patch(f"/api/playlists/{playlist_id}", json={"name": "New"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.get_personal_playlist(playlist_id, self.USER_ID)["name"], "New")


if __name__ == "__main__":
    unittest.main()
