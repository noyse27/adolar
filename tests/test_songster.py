import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-songster-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-songster-import-control.db"),
)

from adolar import application as app_module
from adolar import auth, db, songster


class SongsterTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()


class SongsterSettingsTests(SongsterTestBase):
    def test_defaults_to_disabled(self):
        self.assertEqual(songster.get_global_settings(), {"enabled": False})

    def test_update_and_read_back(self):
        result = songster.update_global_settings({"enabled": True})
        self.assertEqual(result, {"enabled": True})
        self.assertEqual(songster.get_global_settings(), {"enabled": True})

        songster.update_global_settings({"enabled": False})
        self.assertEqual(songster.get_global_settings(), {"enabled": False})

    def test_unknown_keys_are_ignored(self):
        songster.update_global_settings({"unrelated": "value"})
        self.assertEqual(songster.get_global_settings(), {"enabled": False})


class SongsterEnabledColumnTests(SongsterTestBase):
    def test_column_exists_and_defaults_to_zero(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_radio_station(
            "Querbeet", "", {"mode": "all", "rules": []}, user_id, scope="global",
        )
        station = db.get_radio_station(station_id)
        self.assertFalse(station["songster_enabled"])
        self.assertFalse(station["songster_managed"])

    def test_survives_reinitialization(self):
        db.init_db()
        with db.db() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(radio_stations)")}
        self.assertIn("songster_enabled", columns)
        self.assertIn("songster_managed", columns)


class SongsterStationVisibilityTests(SongsterTestBase):
    def test_songster_managed_station_is_excluded_from_the_normal_station_list_even_when_not_yet_enabled(self):
        # A freshly created songster playlist (songster_managed=1,
        # songster_enabled=0, i.e. not yet freigeschaltet) must still be
        # hidden from the normal Adolar view - only songster_managed governs
        # this exclusion, not songster_enabled (see concept doc 3.2/3.3).
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_songster_playlist("HipHop", "", {"mode": "all", "rules": []}, user_id)

        visible = db.list_radio_stations()
        self.assertNotIn("HipHop", [s["name"] for s in visible])

        # Direct lookup by id (used by the edit/delete/play routes) is
        # intentionally not filtered - only the general listing is.
        self.assertIsNotNone(db.get_radio_station(station_id))

    def test_songster_managed_station_stays_excluded_once_enabled(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_songster_playlist("HipHop", "", {"mode": "all", "rules": []}, user_id)
        db.set_songster_playlist_enabled(station_id, True)

        visible = db.list_radio_stations()
        self.assertNotIn("HipHop", [s["name"] for s in visible])

    def test_normal_stations_are_unaffected(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        db.create_radio_station("Bravo", "", {"mode": "all", "rules": []}, user_id, scope="global")
        visible = db.list_radio_stations()
        self.assertIn("Bravo", [s["name"] for s in visible])


class SongsterAdminPlaylistManagementTests(SongsterTestBase):
    def test_create_songster_playlist_starts_disabled_and_global(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_songster_playlist("Querbeet", "desc", {"mode": "all", "rules": []}, user_id)
        station = db.get_radio_station(station_id)
        self.assertTrue(station["songster_managed"])
        self.assertFalse(station["songster_enabled"])
        self.assertEqual(station["scope"], "global")

    def test_set_songster_playlist_enabled_toggles_and_is_scoped_to_songster_managed_stations(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        playlist_id = db.create_songster_playlist("Querbeet", "", {"mode": "all", "rules": []}, user_id)
        normal_id = db.create_radio_station(
            "Normal", "", {"mode": "all", "rules": []}, user_id, scope="global",
        )

        self.assertTrue(db.set_songster_playlist_enabled(playlist_id, True))
        self.assertTrue(db.get_radio_station(playlist_id)["songster_enabled"])

        self.assertTrue(db.set_songster_playlist_enabled(playlist_id, False))
        self.assertFalse(db.get_radio_station(playlist_id)["songster_enabled"])

        # A normal (non-songster) station can't be toggled through this path.
        self.assertFalse(db.set_songster_playlist_enabled(normal_id, True))
        self.assertFalse(db.get_radio_station(normal_id)["songster_enabled"])

    def test_list_songster_admin_playlists_shows_all_regardless_of_enabled(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        db.create_songster_playlist("Disabled", "", {"mode": "all", "rules": []}, user_id)
        enabled_id = db.create_songster_playlist("Enabled", "", {"mode": "all", "rules": []}, user_id)
        db.set_songster_playlist_enabled(enabled_id, True)
        db.create_radio_station("Normal", "", {"mode": "all", "rules": []}, user_id, scope="global")

        names = {p["name"] for p in db.list_songster_admin_playlists()}
        self.assertEqual(names, {"Disabled", "Enabled"})

    def test_list_songster_playlists_game_client_view_requires_both_flags(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        db.create_songster_playlist("Disabled", "", {"mode": "all", "rules": []}, user_id)
        enabled_id = db.create_songster_playlist("Enabled", "", {"mode": "all", "rules": []}, user_id)
        db.set_songster_playlist_enabled(enabled_id, True)

        names = {p["name"] for p in db.list_songster_playlists()}
        self.assertEqual(names, {"Enabled"})


class SongsterRouteTests(SongsterTestBase):
    def setUp(self):
        super().setUp()
        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.user_id = auth.create_user("listener", "password123", role="user")
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "token")

    def _login(self, user_id):
        return mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(user_id), must_change_password=0),
        )

    def test_status_is_readable_by_any_logged_in_user(self):
        with self._login(self.user_id):
            response = self.client.get("/api/songster/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"enabled": False})

    def test_status_requires_login(self):
        anon_client = app_module.app.test_client()
        response = anon_client.get("/api/songster/status")
        self.assertNotEqual(response.status_code, 200)

    def test_admin_settings_require_admin(self):
        with self._login(self.user_id):
            denied = self.client.put("/api/admin/songster/settings", json={"enabled": True})
        self.assertEqual(denied.status_code, 403)

        with self._login(self.admin_id):
            allowed = self.client.put("/api/admin/songster/settings", json={"enabled": True})
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.get_json()["enabled"])

        with self._login(self.user_id):
            get_denied = self.client.get("/api/admin/songster/settings")
        self.assertEqual(get_denied.status_code, 403)

    def test_admin_settings_round_trip_reflected_in_status(self):
        with self._login(self.admin_id):
            self.client.put("/api/admin/songster/settings", json={"enabled": True})
        with self._login(self.user_id):
            status = self.client.get("/api/songster/status").get_json()
        self.assertEqual(status, {"enabled": True})

    def test_admin_settings_rejects_unknown_keys_and_non_bool_values(self):
        with self._login(self.admin_id):
            bad_key = self.client.put("/api/admin/songster/settings", json={"nope": True})
            self.assertEqual(bad_key.status_code, 400)

            bad_value = self.client.put("/api/admin/songster/settings", json={"enabled": "yes"})
            self.assertEqual(bad_value.status_code, 400)


class SongsterPlaylistTrackListingTests(SongsterTestBase):
    def test_returns_none_for_non_songster_station(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_radio_station(
            "Querbeet", "", {"mode": "all", "rules": []}, user_id, scope="global",
        )
        self.assertIsNone(db.list_songster_playlist_tracks(station_id))

    def test_returns_none_for_songster_managed_but_not_yet_enabled_station(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_songster_playlist("Querbeet", "", {"mode": "all", "rules": []}, user_id)
        self.assertIsNone(db.list_songster_playlist_tracks(station_id))

    def test_returns_paginated_tracks_for_songster_station(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_songster_playlist("Querbeet", "", {"mode": "all", "rules": []}, user_id)
        db.set_songster_playlist_enabled(station_id, True)
        with db.db() as conn:
            for i in range(3):
                conn.execute(
                    """INSERT INTO tracks (path, title, artist, album, year, duration)
                       VALUES (?,?,?,?,?,?)""",
                    (f"/music/t{i}.mp3", f"Track {i}", f"Artist {i}", "Album", 1990 + i, 180),
                )
        result = db.list_songster_playlist_tracks(station_id, limit=2, offset=0)
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["tracks"]), 2)
        self.assertEqual(result["tracks"][0]["title"], "Track 0")

        page2 = db.list_songster_playlist_tracks(station_id, limit=2, offset=2)
        self.assertEqual(len(page2["tracks"]), 1)
        self.assertEqual(page2["tracks"][0]["title"], "Track 2")


class SongsterGameClientRouteTests(SongsterTestBase):
    def setUp(self):
        super().setUp()
        # HTTP requests (unlike direct db.* calls above) go through
        # application.py's before_request, which binds library_context to
        # the *registry's* active library rather than db.DB_PATH directly
        # (see adolar/library_context.py) - the registry file must be
        # redirected into the test's temp dir too, or the request would
        # silently read/write a completely different (real) database.
        self.registry_patch = mock.patch.object(
            app_module, "LIBRARY_REGISTRY_PATH", os.path.join(self.temp.name, "libraries.json"),
        )
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.station_id = db.create_songster_playlist(
            "Querbeet", "", {"mode": "all", "rules": []}, self.admin_id,
        )
        db.set_songster_playlist_enabled(self.station_id, True)
        songster.update_global_settings({"enabled": True})
        self.songster_token = auth.create_api_token(self.admin_id, "Songster Game Server", product="songster")
        self.taggster_token = auth.create_api_token(self.admin_id, "Taggster", product="taggster")
        self.client = app_module.app.test_client()

    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_playlists_requires_songster_token(self):
        anon = self.client.get("/api/songster/playlists")
        self.assertEqual(anon.status_code, 401)

        wrong_product = self.client.get("/api/songster/playlists", headers=self._bearer(self.taggster_token))
        self.assertEqual(wrong_product.status_code, 401)

    def test_playlists_lists_songster_enabled_stations(self):
        response = self.client.get("/api/songster/playlists", headers=self._bearer(self.songster_token))
        self.assertEqual(response.status_code, 200)
        playlists = response.get_json()["playlists"]
        self.assertEqual([p["name"] for p in playlists], ["Querbeet"])

    def test_playlists_rejected_when_globally_disabled(self):
        songster.update_global_settings({"enabled": False})
        response = self.client.get("/api/songster/playlists", headers=self._bearer(self.songster_token))
        self.assertEqual(response.status_code, 403)

    def test_playlist_tracks_paginated(self):
        with db.db() as conn:
            for i in range(3):
                conn.execute(
                    """INSERT INTO tracks (path, title, artist, album, year, duration)
                       VALUES (?,?,?,?,?,?)""",
                    (f"/music/t{i}.mp3", f"Track {i}", f"Artist {i}", "Album", 1990 + i, 180),
                )
        response = self.client.get(
            f"/api/songster/playlists/{self.station_id}/tracks?limit=2&offset=0",
            headers=self._bearer(self.songster_token),
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["tracks"]), 2)

    def test_playlist_tracks_404_for_unknown_or_non_songster_station(self):
        other_station = db.create_radio_station(
            "Normal", "", {"mode": "all", "rules": []}, self.admin_id, scope="global",
        )
        response = self.client.get(
            f"/api/songster/playlists/{other_station}/tracks",
            headers=self._bearer(self.songster_token),
        )
        self.assertEqual(response.status_code, 404)

        missing = self.client.get(
            "/api/songster/playlists/999999/tracks", headers=self._bearer(self.songster_token),
        )
        self.assertEqual(missing.status_code, 404)


class SongsterAdminPlaylistRouteTests(SongsterTestBase):
    """The browser-session-authenticated "Songster Playlists" admin dialog
    routes (Step 3) - distinct from the Bearer-token game-client routes
    tested above."""

    def setUp(self):
        super().setUp()
        self.registry_patch = mock.patch.object(
            app_module, "LIBRARY_REGISTRY_PATH", os.path.join(self.temp.name, "libraries.json"),
        )
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.user_id = auth.create_user("listener", "password123", role="user")
        self.client = app_module.app.test_client()

    def _login(self, user_id):
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(user_id), must_change_password=0),
        )

    def test_list_requires_admin(self):
        with self._login(self.user_id):
            denied = self.client.get("/api/admin/songster/playlists")
        self.assertEqual(denied.status_code, 403)

    def test_create_starts_disabled_and_excluded_from_normal_view(self):
        with self._login(self.admin_id):
            response = self.client.post(
                "/api/admin/songster/playlists",
                json={"name": "Querbeet", "description": "", "filter": {"mode": "all", "rules": []}},
            )
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertTrue(body["songster_managed"])
        self.assertFalse(body["songster_enabled"])
        self.assertEqual(body["scope"], "global")

        with self._login(self.admin_id):
            listing = self.client.get("/api/admin/songster/playlists").get_json()
        self.assertEqual([p["name"] for p in listing], ["Querbeet"])

        with self._login(self.admin_id):
            normal_view = self.client.get("/api/radio-stations").get_json()
        self.assertNotIn("Querbeet", [s["name"] for s in normal_view])

    def test_create_requires_name(self):
        with self._login(self.admin_id):
            response = self.client.post("/api/admin/songster/playlists", json={"name": "  "})
        self.assertEqual(response.status_code, 400)

    def test_enable_toggle_round_trip(self):
        with self._login(self.admin_id):
            playlist_id = self.client.post(
                "/api/admin/songster/playlists", json={"name": "Querbeet"},
            ).get_json()["id"]

            enable = self.client.put(
                f"/api/admin/songster/playlists/{playlist_id}/enabled", json={"enabled": True},
            )
            self.assertEqual(enable.status_code, 200)
            self.assertTrue(enable.get_json()["songster_enabled"])

            disable = self.client.put(
                f"/api/admin/songster/playlists/{playlist_id}/enabled", json={"enabled": False},
            )
            self.assertFalse(disable.get_json()["songster_enabled"])

    def test_enable_toggle_rejects_non_songster_station(self):
        with self._login(self.admin_id):
            normal_id = self.client.post(
                "/api/radio-stations", json={"name": "Normal", "scope": "global"},
            ).get_json()["id"]
            response = self.client.put(
                f"/api/admin/songster/playlists/{normal_id}/enabled", json={"enabled": True},
            )
        self.assertEqual(response.status_code, 404)

    def test_enable_toggle_requires_boolean(self):
        with self._login(self.admin_id):
            playlist_id = self.client.post(
                "/api/admin/songster/playlists", json={"name": "Querbeet"},
            ).get_json()["id"]
            response = self.client.put(
                f"/api/admin/songster/playlists/{playlist_id}/enabled", json={"enabled": "yes"},
            )
        self.assertEqual(response.status_code, 400)

    def test_update_edits_name_and_filter(self):
        with self._login(self.admin_id):
            playlist_id = self.client.post(
                "/api/admin/songster/playlists", json={"name": "Querbeet"},
            ).get_json()["id"]
            response = self.client.put(
                f"/api/admin/songster/playlists/{playlist_id}",
                json={"name": "Renamed", "description": "new desc", "filter": {"mode": "all", "rules": []}},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Renamed")

    def test_update_rejects_non_songster_station(self):
        with self._login(self.admin_id):
            normal_id = self.client.post(
                "/api/radio-stations", json={"name": "Normal", "scope": "global"},
            ).get_json()["id"]
            response = self.client.put(
                f"/api/admin/songster/playlists/{normal_id}", json={"name": "Hijacked"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(db.get_radio_station(normal_id)["name"], "Normal")

    def test_delete_removes_playlist(self):
        with self._login(self.admin_id):
            playlist_id = self.client.post(
                "/api/admin/songster/playlists", json={"name": "Querbeet"},
            ).get_json()["id"]
            response = self.client.delete(f"/api/admin/songster/playlists/{playlist_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.get_radio_station(playlist_id))

    def test_delete_rejects_non_songster_station(self):
        with self._login(self.admin_id):
            normal_id = self.client.post(
                "/api/radio-stations", json={"name": "Normal", "scope": "global"},
            ).get_json()["id"]
            response = self.client.delete(f"/api/admin/songster/playlists/{normal_id}")
        self.assertEqual(response.status_code, 404)
        self.assertIsNotNone(db.get_radio_station(normal_id))


class SongsterTrackStreamRouteTests(SongsterTestBase):
    def setUp(self):
        super().setUp()
        self.registry_patch = mock.patch.object(
            app_module, "LIBRARY_REGISTRY_PATH", os.path.join(self.temp.name, "libraries.json"),
        )
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

        self.music_root = os.path.join(self.temp.name, "music")
        os.makedirs(self.music_root)
        self.music_root_patch = mock.patch.object(app_module, "MUSIC_ROOT", self.music_root)
        self.music_root_patch.start()
        self.addCleanup(self.music_root_patch.stop)

        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.station_id = db.create_songster_playlist(
            "Querbeet", "", {"mode": "all", "rules": []}, self.admin_id,
        )
        db.set_songster_playlist_enabled(self.station_id, True)
        songster.update_global_settings({"enabled": True})
        self.songster_token = auth.create_api_token(self.admin_id, "Songster Game Server", product="songster")
        self.taggster_token = auth.create_api_token(self.admin_id, "Taggster", product="taggster")
        self.client = app_module.app.test_client()

        self.content = b"0123456789" * 10  # 100 bytes
        full_path = os.path.join(self.music_root, "song.mp3")
        with open(full_path, "wb") as f:
            f.write(self.content)
        with db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path, title) VALUES ('song.mp3', 'Song')")
            self.track_id = cur.lastrowid

    def _bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_requires_songster_token(self):
        anon = self.client.get(f"/api/songster/tracks/{self.track_id}/stream")
        self.assertEqual(anon.status_code, 401)

        wrong_product = self.client.get(
            f"/api/songster/tracks/{self.track_id}/stream", headers=self._bearer(self.taggster_token),
        )
        self.assertEqual(wrong_product.status_code, 401)

    def test_rejected_when_globally_disabled(self):
        songster.update_global_settings({"enabled": False})
        response = self.client.get(
            f"/api/songster/tracks/{self.track_id}/stream", headers=self._bearer(self.songster_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_streams_full_track(self):
        response = self.client.get(
            f"/api/songster/tracks/{self.track_id}/stream", headers=self._bearer(self.songster_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "audio/mpeg")
        self.assertEqual(response.data, self.content)

    def test_range_request_returns_partial_content(self):
        response = self.client.get(
            f"/api/songster/tracks/{self.track_id}/stream",
            headers={**self._bearer(self.songster_token), "Range": "bytes=10-19"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, self.content[10:20])

    def test_missing_track_returns_404(self):
        response = self.client.get(
            "/api/songster/tracks/999999/stream", headers=self._bearer(self.songster_token),
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
