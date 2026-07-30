import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-unicode-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-unicode-import-control.db"),
)

import db


class UnicodeCasefoldSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        with db.db() as conn:
            conn.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'u1', 'x')")
            conn.execute(
                "INSERT INTO tracks (path, artist, title, album) VALUES (?, ?, ?, ?)",
                ("/a.mp3", "Кино", "Группа крови", "Группа крови"),
            )

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_lowercase_cyrillic_query_matches_uppercase_cyrillic_artist(self):
        # SQLite's built-in LOWER() only folds ASCII, so a plain LOWER()-based
        # filter would never match "Кино" against a lowercase "кино" query.
        total, tracks = db.search_tracks(artist_query="кино")
        self.assertEqual(total, 1)
        self.assertEqual(tracks[0]["artist"], "Кино")

    def test_uppercase_cyrillic_query_matches_via_album_eq(self):
        total, tracks = db.search_tracks(album_eq="ГРУППА КРОВИ")
        self.assertEqual(total, 1)
