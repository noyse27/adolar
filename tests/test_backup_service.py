import hashlib
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

import backup_service


class BackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "live.db"
        self.backups = self.root / "backups"
        self.jingles = self.root / "radio_jingles"
        self.jingles.mkdir()
        (self.jingles / "station-1.mp3").write_bytes(b"jingle audio")

        conn = sqlite3.connect(self.database)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.executemany("INSERT INTO tracks(title) VALUES (?)", [("One",), ("Two",)])
        conn.execute("INSERT INTO users(username) VALUES ('admin')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_creates_verified_snapshot_and_jingle_archive(self):
        result = backup_service.create_backup(
            str(self.database), str(self.backups),
            jingle_root=str(self.jingles), app_version="test", retention=7,
        )
        directory = self.backups / result["backup_id"]
        snapshot = directory / "adolar.db"
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))

        self.assertTrue(snapshot.is_file())
        self.assertEqual(manifest["database"]["quick_check"], "ok")
        self.assertEqual(manifest["database"]["counts"]["tracks"], 2)
        self.assertIsNone(manifest["control_database"])
        self.assertEqual(
            manifest["database"]["sha256"],
            hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        )
        with tarfile.open(directory / "radio-jingles.tar.gz", "r:gz") as archive:
            self.assertEqual(archive.getnames(), ["station-1.mp3"])

        check = sqlite3.connect(snapshot)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 2)
        check.close()
        self.assertFalse(any(self.backups.glob("*.partial")))

    def test_control_database_is_snapshotted_and_counted_separately(self):
        control_db = self.root / "control.db"
        conn = sqlite3.connect(control_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("INSERT INTO users(username) VALUES ('admin')")
        conn.commit()
        conn.close()

        result = backup_service.create_backup(
            str(self.database), str(self.backups),
            control_db_path=str(control_db), app_version="test", retention=7,
        )
        directory = self.backups / result["backup_id"]
        control_snapshot = directory / "control.db"

        self.assertTrue(control_snapshot.is_file())
        self.assertEqual(result["control_database"]["quick_check"], "ok")
        self.assertEqual(result["control_database"]["counts"]["users"], 1)
        self.assertEqual(
            result["control_database"]["sha256"],
            hashlib.sha256(control_snapshot.read_bytes()).hexdigest(),
        )

    def test_list_download_and_delete_reject_unsafe_ids(self):
        result = backup_service.create_backup(str(self.database), str(self.backups))
        backup_id = result["backup_id"]
        listed = backup_service.list_backups(str(self.backups))
        self.assertEqual([item["backup_id"] for item in listed], [backup_id])
        self.assertEqual(
            backup_service.get_backup_file(str(self.backups), backup_id).name,
            "adolar.db",
        )
        with self.assertRaises(FileNotFoundError):
            backup_service.get_backup_file(str(self.backups), "../outside")
        backup_service.delete_backup(str(self.backups), backup_id)
        self.assertEqual(backup_service.list_backups(str(self.backups)), [])

    def test_missing_database_never_creates_empty_backup(self):
        with self.assertRaises(backup_service.BackupError):
            backup_service.create_backup(
                str(self.root / "missing.db"), str(self.backups),
            )
        self.assertFalse(self.backups.exists())


if __name__ == "__main__":
    unittest.main()
