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

    def test_survives_reinitialization(self):
        db.init_db()
        with db.db() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(radio_stations)")}
        self.assertIn("songster_enabled", columns)


class SongsterStationVisibilityTests(SongsterTestBase):
    def test_songster_enabled_station_is_excluded_from_the_normal_station_list(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        station_id = db.create_radio_station(
            "HipHop", "", {"mode": "all", "rules": []}, user_id, scope="global",
        )
        with db.db() as conn:
            conn.execute("UPDATE radio_stations SET songster_enabled=1 WHERE id=?", (station_id,))

        visible = db.list_radio_stations()
        self.assertNotIn("HipHop", [s["name"] for s in visible])

        # Direct lookup by id (used by the edit/delete/play routes) is
        # intentionally not filtered - only the general listing is.
        self.assertIsNotNone(db.get_radio_station(station_id))

    def test_normal_stations_are_unaffected(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        db.create_radio_station("Bravo", "", {"mode": "all", "rules": []}, user_id, scope="global")
        visible = db.list_radio_stations()
        self.assertIn("Bravo", [s["name"] for s in visible])


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


if __name__ == "__main__":
    unittest.main()
