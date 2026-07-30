import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-scanroutes-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-scanroutes-import-control.db"),
)

import app as app_module


class ScanRouteTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music_root = os.path.join(self.temp.name, "music")
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

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _login(self, role="user"):
        user = {
            "id": 1, "username": "u", "role": role, "allow_download": 0,
            "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
            "is_active": 1, "must_change_password": 0,
        }
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user)


class ScanStartRouteTests(ScanRouteTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.post("/api/scan/start")
        self.assertEqual(response.status_code, 403)

    def test_missing_music_root_returns_400(self):
        with self._login(role="admin"):
            response = self.client.post("/api/scan/start")
        self.assertEqual(response.status_code, 400)
        self.assertIn(self.music_root, response.get_json()["error"])

    def test_existing_music_root_starts_the_scan(self):
        os.makedirs(self.music_root)
        with self._login(role="admin"), mock.patch.object(app_module.scanner, "run_scan") as run_scan:
            response = self.client.post("/api/scan/start")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "started")
        run_scan.assert_called_once_with(self.music_root)


class BpmTagsRouteTests(ScanRouteTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.post("/api/scan/bpm-tags")
        self.assertEqual(response.status_code, 403)

    def test_returns_started_immediately(self):
        with self._login(role="admin"), mock.patch.object(
            app_module, "_start_library_thread",
        ) as start_thread:
            response = self.client.post("/api/scan/bpm-tags")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "started")
        start_thread.assert_called_once()


class BpmScanRouteTests(ScanRouteTestBase):
    def test_requires_admin(self):
        with self._login():
            response = self.client.post("/api/scan/bpm")
        self.assertEqual(response.status_code, 403)

    def test_default_limit_is_reported_as_unlimited(self):
        with self._login(role="admin"), mock.patch.object(app_module.scanner, "run_bpm_scan") as run_bpm:
            response = self.client.post("/api/scan/bpm")
        self.assertEqual(response.get_json()["limit"], "unlimited")
        run_bpm.assert_called_once_with(0)

    def test_explicit_limit_is_forwarded_to_the_scanner(self):
        with self._login(role="admin"), mock.patch.object(app_module.scanner, "run_bpm_scan") as run_bpm:
            response = self.client.post("/api/scan/bpm", json={"limit": 100})
        self.assertEqual(response.get_json()["limit"], 100)
        run_bpm.assert_called_once_with(100)


class ScanStatusRouteTests(ScanRouteTestBase):
    def test_requires_authentication(self):
        response = self.client.get("/api/scan/status")
        self.assertEqual(response.status_code, 401)

    def test_merges_scanner_status_and_db_track_count(self):
        with app_module.db.db() as conn:
            conn.execute("INSERT INTO tracks (path) VALUES ('/a.mp3')")
        with self._login():
            response = self.client.get("/api/scan/status")
        data = response.get_json()
        self.assertEqual(data["total_tracks"], 1)
        self.assertIn("running", data)

    def test_persisted_scan_time_is_returned_after_process_restart(self):
        app_module.db.set_last_scan_finished_at(1_722_085_200.5)
        with self._login(), mock.patch.object(
            app_module.scanner,
            "status",
            return_value={"running": False, "finished_at": None},
        ):
            scan_status = self.client.get("/api/scan/status").get_json()
            stats = self.client.get("/api/stats").get_json()

        self.assertEqual(scan_status["finished_at"], 1_722_085_200.5)
        self.assertEqual(stats["last_scan"], 1_722_085_200.5)


if __name__ == "__main__":
    unittest.main()
