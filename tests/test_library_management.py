import os
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar-library-mgmt-import.db"))

from adolar import application as app_module
from adolar.routes import admin as admin_routes


class LibraryManagementTests(unittest.TestCase):
    ADMIN_ID = 81

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # Forward-slash paths: production always runs in Linux/Docker, and
        # db.migrate_track_paths deliberately matches "/" rather than
        # os.sep — Windows accepts "/" paths fine, so this keeps the test
        # realistic without needing a POSIX host.
        temp_posix = self.temp.name.replace("\\", "/")
        self.music_root = f"{temp_posix}/music"
        os.makedirs(self.music_root)
        self.db_path = os.path.join(self.temp.name, "adolar.db")

        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", self.db_path),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
            mock.patch.object(app_module, "MUSIC_ROOT", self.music_root),
            mock.patch.object(
                app_module, "LIBRARY_REGISTRY_PATH",
                os.path.join(self.temp.name, "libraries.json"),
            ),
            mock.patch.object(
                app_module, "LIBRARIES_DIR", os.path.join(self.temp.name, "libraries"),
            ),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO users (id, username, password_hash, role, must_change_password)
                   VALUES (?, 'admin', 'unused', 'admin', 0)""",
                (self.ADMIN_ID,),
            )

        self.admin = {
            "id": self.ADMIN_ID,
            "username": "admin",
            "role": "admin",
            "allow_download": 1,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.user = dict(self.admin, id=82, username="listener", role="user")
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "library-mgmt-token")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _as(self, actor):
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=actor)

    def test_list_requires_admin(self):
        with self._as(self.user):
            response = self.client.get("/api/admin/libraries")
        self.assertEqual(response.status_code, 403)

    def test_list_seeds_a_default_library_from_current_paths(self):
        with self._as(self.admin):
            response = self.client.get("/api/admin/libraries")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["libraries"]), 1)
        self.assertEqual(data["libraries"][0]["music_path"], self.music_root)
        self.assertEqual(data["active_id"], data["libraries"][0]["id"])

    def test_create_rejects_missing_path(self):
        with self._as(self.admin):
            response = self.client.post("/api/admin/libraries", json={
                "name": "Zweit", "music_path": os.path.join(self.temp.name, "does-not-exist"),
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Verzeichnis", response.get_json()["error"])

    def test_create_activates_new_library_and_switches_content_db(self):
        new_music_path = os.path.join(self.temp.name, "music2")
        os.makedirs(new_music_path)
        with self._as(self.admin):
            response = self.client.post("/api/admin/libraries", json={
                "name": "Zweitbibliothek", "music_path": new_music_path,
            })
        self.assertEqual(response.status_code, 201)
        lib = response.get_json()
        self.assertEqual(lib["music_path"], new_music_path)
        active = app_module.libraries.get_active(
            app_module.LIBRARY_REGISTRY_PATH,
            app_module.MUSIC_ROOT,
            app_module.db.DB_PATH,
        )
        self.assertEqual(active, lib)
        # Process defaults deliberately remain unchanged; every worker reads
        # the shared registry at the start of its next request.
        self.assertEqual(app_module.MUSIC_ROOT, self.music_root)
        self.assertEqual(app_module.db.DB_PATH, self.db_path)
        self.assertTrue(os.path.exists(lib["db_path"]))

        with (
            app_module.library_context.bind(lib["db_path"], lib["music_path"]),
            app_module.db.db() as conn,
        ):
            conn.execute("INSERT INTO tracks (path, title) VALUES ('/new.mp3', 'New')")
        # This next request models another Gunicorn worker: its process
        # defaults are still the original library, but the shared registry
        # selects the newly active content database.
        with self._as(self.admin):
            status = self.client.get("/api/scan/status").get_json()
        self.assertEqual(status["total_tracks"], 1)

    def test_activate_switches_back_to_original_library(self):
        new_music_path = os.path.join(self.temp.name, "music2")
        os.makedirs(new_music_path)
        with self._as(self.admin):
            created = self.client.post("/api/admin/libraries", json={
                "name": "Zweitbibliothek", "music_path": new_music_path,
            }).get_json()
            listing = self.client.get("/api/admin/libraries").get_json()
            original_id = next(
                lib["id"] for lib in listing["libraries"] if lib["id"] != created["id"]
            )
            response = self.client.post(f"/api/admin/libraries/{original_id}/activate")
        self.assertEqual(response.status_code, 200)
        active = app_module.libraries.get_active(
            app_module.LIBRARY_REGISTRY_PATH,
            app_module.MUSIC_ROOT,
            app_module.db.DB_PATH,
        )
        self.assertEqual(active["id"], original_id)
        self.assertEqual(active["music_path"], self.music_root)
        self.assertEqual(active["db_path"], self.db_path)

    def test_activate_unknown_library_returns_404(self):
        with self._as(self.admin):
            response = self.client.post("/api/admin/libraries/does-not-exist/activate")
        self.assertEqual(response.status_code, 404)

    def test_move_rewrites_track_paths_for_active_library(self):
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (id, path, title) VALUES (1, ?, 'Song')",
                (f"{self.music_root}/song.mp3",),
            )
        temp_posix = self.temp.name.replace("\\", "/")
        new_path = f"{temp_posix}/music-moved"
        os.makedirs(new_path)
        with self._as(self.admin):
            listing = self.client.get("/api/admin/libraries").get_json()
            active_id = listing["active_id"]
            response = self.client.put(
                f"/api/admin/libraries/{active_id}/move",
                json={"new_music_path": new_path},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["tracks_updated"], 1)
        resolved_new_path = os.path.realpath(new_path)
        active = app_module.libraries.get_active(
            app_module.LIBRARY_REGISTRY_PATH,
            app_module.MUSIC_ROOT,
            app_module.db.DB_PATH,
        )
        self.assertEqual(active["music_path"], resolved_new_path)
        with app_module.db.db() as conn:
            path = conn.execute("SELECT path FROM tracks WHERE id=1").fetchone()["path"]
        self.assertTrue(path.startswith(resolved_new_path))

    def test_move_rejects_inactive_library(self):
        new_music_path = os.path.join(self.temp.name, "music2")
        os.makedirs(new_music_path)
        with self._as(self.admin):
            created = self.client.post("/api/admin/libraries", json={
                "name": "Zweitbibliothek", "music_path": new_music_path,
            }).get_json()
            listing = self.client.get("/api/admin/libraries").get_json()
            inactive_id = next(
                lib["id"] for lib in listing["libraries"] if lib["id"] != created["id"]
            )
            response = self.client.put(
                f"/api/admin/libraries/{inactive_id}/move",
                json={"new_music_path": self.temp.name},
            )
        self.assertEqual(response.status_code, 400)

    def test_covers_endpoint_requires_admin_and_starts(self):
        with self._as(self.user):
            forbidden = self.client.post("/api/admin/library/covers")
        self.assertEqual(forbidden.status_code, 403)
        with self._as(self.admin), mock.patch.object(admin_routes.scanner, "run_thumb_generation") as run:
            response = self.client.post("/api/admin/library/covers")
        self.assertEqual(response.status_code, 200)
        run.assert_called_once()

    def test_optimize_endpoint_requires_admin_and_reports_both_databases(self):
        with self._as(self.user):
            forbidden = self.client.post("/api/admin/database/optimize")
        self.assertEqual(forbidden.status_code, 403)
        with self._as(self.admin):
            response = self.client.post("/api/admin/database/optimize")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["content"]["integrity_check"], "ok")
        self.assertEqual(data["control"]["integrity_check"], "ok")


if __name__ == "__main__":
    unittest.main()
