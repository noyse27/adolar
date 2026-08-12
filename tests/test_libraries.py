import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-libraries-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-libraries-import-control.db"),
)

from adolar import db, errors, libraries


class LibraryRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry_path = os.path.join(self.temp.name, "libraries.json")
        self.libraries_dir = os.path.join(self.temp.name, "libraries")
        self.music_root = os.path.join(self.temp.name, "music")
        self.db_path = os.path.join(self.temp.name, "adolar.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_first_load_seeds_registry_from_current_paths(self):
        libs, active_id = libraries.list_libraries(self.registry_path, self.music_root, self.db_path)
        self.assertEqual(len(libs), 1)
        self.assertEqual(libs[0]["music_path"], self.music_root)
        self.assertEqual(libs[0]["db_path"], self.db_path)
        self.assertEqual(libs[0]["id"], active_id)
        self.assertTrue(os.path.exists(self.registry_path))

    def test_seed_only_happens_once(self):
        libraries.load_registry(self.registry_path, self.music_root, self.db_path)
        # Second load with different current paths must not reseed/overwrite.
        libs, _ = libraries.list_libraries(self.registry_path, "/somewhere/else", "/other.db")
        self.assertEqual(libs[0]["music_path"], self.music_root)

    def test_add_library_creates_new_active_entry_with_managed_db_path(self):
        libraries.load_registry(self.registry_path, self.music_root, self.db_path)
        new_music_path = os.path.join(self.temp.name, "music2")
        lib = libraries.add_library(
            self.registry_path, self.music_root, self.db_path,
            self.libraries_dir, "Zweitbibliothek", new_music_path,
        )
        self.assertEqual(lib["music_path"], new_music_path)
        self.assertTrue(lib["db_path"].startswith(self.libraries_dir))
        libs, active_id = libraries.list_libraries(self.registry_path, self.music_root, self.db_path)
        self.assertEqual(len(libs), 2)
        self.assertEqual(active_id, lib["id"])

    def test_set_active_switches_active_library(self):
        libraries.load_registry(self.registry_path, self.music_root, self.db_path)
        new_lib = libraries.add_library(
            self.registry_path, self.music_root, self.db_path,
            self.libraries_dir, "Zweitbibliothek", os.path.join(self.temp.name, "music2"),
        )
        first_id = [
            lib["id"] for lib in libraries.list_libraries(
                self.registry_path, self.music_root, self.db_path,
            )[0] if lib["id"] != new_lib["id"]
        ][0]
        activated = libraries.set_active(self.registry_path, self.music_root, self.db_path, first_id)
        self.assertEqual(activated["id"], first_id)
        _, active_id = libraries.list_libraries(self.registry_path, self.music_root, self.db_path)
        self.assertEqual(active_id, first_id)

    def test_set_active_rejects_unknown_id(self):
        libraries.load_registry(self.registry_path, self.music_root, self.db_path)
        with self.assertRaises(errors.ValidationError):
            libraries.set_active(self.registry_path, self.music_root, self.db_path, "nope")

    def test_update_music_path_rewrites_registry_entry(self):
        libs, active_id = libraries.list_libraries(self.registry_path, self.music_root, self.db_path)
        new_path = os.path.join(self.temp.name, "music-moved")
        updated = libraries.update_music_path(
            self.registry_path, self.music_root, self.db_path, active_id, new_path,
        )
        self.assertEqual(updated["music_path"], new_path)
        libs, _ = libraries.list_libraries(self.registry_path, self.music_root, self.db_path)
        self.assertEqual(libs[0]["music_path"], new_path)

    def test_update_music_path_rejects_unknown_id(self):
        libraries.load_registry(self.registry_path, self.music_root, self.db_path)
        with self.assertRaises(errors.ValidationError):
            libraries.update_music_path(self.registry_path, self.music_root, self.db_path, "nope", "/x")


class MigrateTrackPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            db, "DB_PATH", os.path.join(self.temp.name, "migrate-test.db"),
        )
        self.control_db_patch = mock.patch.object(
            db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "migrate-test-control.db"),
        )
        self.db_patch.start()
        self.control_db_patch.start()
        db.init_db()
        with db.db() as conn:
            conn.executemany(
                "INSERT INTO tracks (id, path, title) VALUES (?,?,?)",
                [
                    (1, "/music/rock/song1.mp3", "Song 1"),
                    (2, "/music/jazz/song2.mp3", "Song 2"),
                    (3, "/other/place/song3.mp3", "Song 3"),
                ],
            )

    def tearDown(self):
        self.db_patch.stop()
        self.control_db_patch.stop()
        self.temp.cleanup()

    def test_rewrites_paths_under_old_root_only(self):
        updated = db.migrate_track_paths("/music", "/newmusic")
        self.assertEqual(updated, 2)
        with db.db() as conn:
            rows = {row["id"]: row["path"] for row in conn.execute("SELECT id, path FROM tracks")}
        self.assertEqual(rows[1], "/newmusic/rock/song1.mp3")
        self.assertEqual(rows[2], "/newmusic/jazz/song2.mp3")
        self.assertEqual(rows[3], "/other/place/song3.mp3")

    def test_trailing_slash_on_old_root_is_tolerated(self):
        updated = db.migrate_track_paths("/music/", "/newmusic")
        self.assertEqual(updated, 2)


class OptimizeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            db, "DB_PATH", os.path.join(self.temp.name, "optimize-test.db"),
        )
        self.control_db_patch = mock.patch.object(
            db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "optimize-test-control.db"),
        )
        self.db_patch.start()
        self.control_db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.control_db_patch.stop()
        self.temp.cleanup()

    def test_checks_and_vacuums_both_databases(self):
        result = db.optimize_database()
        self.assertEqual(result["content"]["integrity_check"], "ok")
        self.assertTrue(result["content"]["vacuumed"])
        self.assertEqual(result["control"]["integrity_check"], "ok")
        self.assertTrue(result["control"]["vacuumed"])

    def test_leaves_data_intact(self):
        with db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (id, path, title) VALUES (1, '/music/a.mp3', 'A')",
            )
        db.optimize_database()
        with db.db() as conn:
            count = conn.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
