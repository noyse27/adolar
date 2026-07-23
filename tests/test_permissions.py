import os
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar-permissions-test.db"))

import app as app_module


class SafeNextUrlTests(unittest.TestCase):
    def test_same_origin_paths_are_preserved(self):
        self.assertEqual(app_module._safe_next_url("/miniplayer"), "/miniplayer")
        self.assertEqual(app_module._safe_next_url("/radio?station=3"), "/radio?station=3")
        self.assertEqual(app_module._safe_next_url(None), "/")
        self.assertEqual(app_module._safe_next_url(""), "/")

    def test_external_redirect_targets_are_neutralized(self):
        self.assertEqual(app_module._safe_next_url("https://evil.com/x"), "/")
        self.assertEqual(app_module._safe_next_url("//evil.com"), "/")
        # Browsers collapse any number of leading slashes to "//host".
        self.assertEqual(app_module._safe_next_url("////evil.com"), "/evil.com")
        self.assertEqual(app_module._safe_next_url("/\\evil.com"), "/")
        self.assertEqual(app_module._safe_next_url("\\\\evil.com"), "/")
        self.assertEqual(app_module._safe_next_url("javascript:alert(1)"), "/")


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.user = {
            "id": 11,
            "username": "listener",
            "role": "user",
            "allow_download": 0,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }

    def _login(self):
        self.client.set_cookie("adolar_session", "permission-test-token")
        return mock.patch.object(
            app_module._auth, "get_user_by_token", return_value=self.user
        )

    def test_anonymous_web_is_opt_in(self):
        with mock.patch.object(app_module._auth, "user_count", return_value=1), \
             mock.patch.object(app_module.db, "get_setting", return_value="0"):
            self.assertEqual(self.client.get("/").status_code, 302)
        with mock.patch.object(app_module._auth, "user_count", return_value=1), \
             mock.patch.object(app_module.db, "get_setting", return_value="1"):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_manual_is_public_even_when_anonymous_web_is_disabled(self):
        with mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.get("/hilfe/manual.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Adolar Handbuch", response.get_data(as_text=True))

    def test_user_playlist_capability_is_enforced_server_side(self):
        self.user["allow_playlists"] = 0
        with self._login(), mock.patch.object(
            app_module.db, "get_setting", return_value="1"
        ):
            response = self.client.post("/api/playlists", json={"name": "Nope"})
        self.assertEqual(response.status_code, 403)

    def test_user_radio_capability_is_enforced_server_side(self):
        self.user["allow_radio_stations"] = 0
        with self._login(), mock.patch.object(
            app_module.db, "get_setting", return_value="1"
        ):
            response = self.client.post("/api/radio-stations", json={"name": "Nope"})
        self.assertEqual(response.status_code, 403)

    def test_maintenance_requires_admin(self):
        with self._login():
            response = self.client.post("/api/scan/start")
        self.assertEqual(response.status_code, 403)

        with self._login():
            response = self.client.get("/api/admin/backups")
        self.assertEqual(response.status_code, 403)

    def test_companion_can_require_login(self):
        with mock.patch.object(
            app_module.db, "get_setting", side_effect=lambda key, default=None: (
                "authenticated" if key == "companion_access" else default
            )
        ):
            response = self.client.get("/radio")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/radio", response.location)


if __name__ == "__main__":
    unittest.main()
