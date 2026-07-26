"""Tests for the album-first browsing view's grouping logic (db.search_albums)
and the schema migration that backs it.

There is no album_artist tag in the schema before this migration — scanner.py
only ever stored the per-track artist — so a various-artists compilation used
to explode into one album card per contributing artist. Fixed by grouping on
(album, folder) instead of (album, artist), and preferring an explicit
album_artist tag for the displayed artist when one was actually read from the
files (falling back to "one card if every track agrees on artist, else
Various Artists" for tracks scanned before the tag existed).
"""

import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-albums-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-albums-import-control.db"),
)

import db  # noqa: E402


class AlbumsTestBase(unittest.TestCase):
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
        self.temp.cleanup()

    def _insert(self, rows):
        with db.db() as conn:
            conn.executemany(
                """INSERT INTO tracks (path, title, artist, album, album_artist, year)
                   VALUES (:path, :title, :artist, :album, :album_artist, :year)""",
                rows,
            )

    def _albums_by_title(self, **kwargs):
        _, albums = db.search_albums(**kwargs)
        return {a["album"]: a for a in albums}


class SingleArtistAlbumTests(AlbumsTestBase):
    def test_normal_album_is_one_card_with_its_artist(self):
        self._insert([
            dict(path="/music/Daft Punk/RAM/01.flac", title="Get Lucky", artist="Daft Punk",
                 album="Random Access Memories", album_artist=None, year=2013),
            dict(path="/music/Daft Punk/RAM/02.flac", title="Lose Yourself to Dance", artist="Daft Punk",
                 album="Random Access Memories", album_artist=None, year=2013),
        ])
        total, albums = db.search_albums()
        self.assertEqual(total, 1)
        self.assertEqual(albums[0]["artist"], "Daft Punk")
        self.assertFalse(albums[0]["various"])
        self.assertEqual(albums[0]["track_count"], 2)
        self.assertEqual(albums[0]["dir"], "/music/Daft Punk/RAM")


class CompilationGroupingTests(AlbumsTestBase):
    def _compilation_rows(self, album_artist_tag):
        return [
            dict(path="/music/Comp/Tribute/01.mp3", title="Enjoy the Silence", artist="In Strict Confidence",
                 album="40 Years - Tribute", album_artist=album_artist_tag, year=2020),
            dict(path="/music/Comp/Tribute/02.mp3", title="Personal Jesus", artist="Leaether Strip",
                 album="40 Years - Tribute", album_artist=album_artist_tag, year=2020),
            dict(path="/music/Comp/Tribute/03.mp3", title="Just Can't Get Enough", artist="Neodyn",
                 album="40 Years - Tribute", album_artist=album_artist_tag, year=2020),
        ]

    def test_compilation_without_album_artist_tag_falls_back_to_distinct_artist_heuristic(self):
        # Legacy data: no album_artist tag at all (NULL) — this is exactly
        # the bug reported against the folder-only version of this feature.
        self._insert(self._compilation_rows(album_artist_tag=None))
        total, albums = db.search_albums()
        self.assertEqual(total, 1, "must not explode into one card per contributing artist")
        self.assertTrue(albums[0]["various"])
        self.assertIsNone(albums[0]["artist"])
        self.assertEqual(albums[0]["track_count"], 3)

    def test_compilation_with_explicit_various_artists_tag_is_various(self):
        self._insert(self._compilation_rows(album_artist_tag="Various Artists"))
        total, albums = db.search_albums()
        self.assertEqual(total, 1)
        self.assertTrue(albums[0]["various"])
        self.assertIsNone(albums[0]["artist"])

    def test_various_artists_sentinel_matching_is_case_insensitive(self):
        self._insert(self._compilation_rows(album_artist_tag="VARIOUS ARTISTS"))
        albums = self._albums_by_title()
        self.assertTrue(albums["40 Years - Tribute"]["various"])

    def test_german_various_artists_sentinel_is_recognized(self):
        self._insert(self._compilation_rows(album_artist_tag="Verschiedene Interpreten"))
        albums = self._albums_by_title()
        self.assertTrue(albums["40 Years - Tribute"]["various"])

    def test_explicit_album_artist_tag_wins_over_distinct_track_artist_count(self):
        # A normal (non-compilation) album can still have several *credited*
        # per-track artists (features, remixes) while every file agrees on
        # album_artist — that must show the real album artist, not "various".
        rows = self._compilation_rows(album_artist_tag="Depeche Mode")
        self._insert(rows)
        albums = self._albums_by_title()
        album = albums["40 Years - Tribute"]
        self.assertFalse(album["various"])
        self.assertEqual(album["artist"], "Depeche Mode")


class DistinctFoldersStayDistinctTests(AlbumsTestBase):
    def test_two_same_titled_albums_by_different_artists_in_different_folders_stay_separate(self):
        self._insert([
            dict(path="/music/Queen/Greatest Hits/01.mp3", title="Bohemian Rhapsody", artist="Queen",
                 album="Greatest Hits", album_artist=None, year=1981),
            dict(path="/music/ABBA/Greatest Hits/01.mp3", title="Dancing Queen", artist="ABBA",
                 album="Greatest Hits", album_artist=None, year=1976),
        ])
        total, albums = db.search_albums()
        self.assertEqual(total, 2)
        artists = {a["artist"] for a in albums}
        self.assertEqual(artists, {"Queen", "ABBA"})
        for a in albums:
            self.assertFalse(a["various"])


class DrillDownExactMatchTests(AlbumsTestBase):
    def test_dir_eq_and_album_eq_select_exactly_that_albums_tracks(self):
        self._insert([
            dict(path="/music/Queen/Greatest Hits/01.mp3", title="Bohemian Rhapsody", artist="Queen",
                 album="Greatest Hits", album_artist=None, year=1981),
            dict(path="/music/ABBA/Greatest Hits/01.mp3", title="Dancing Queen", artist="ABBA",
                 album="Greatest Hits", album_artist=None, year=1976),
        ])
        total, tracks = db.search_tracks(
            album_eq="Greatest Hits", dir_eq="/music/Queen/Greatest Hits",
        )
        self.assertEqual(total, 1)
        self.assertEqual(tracks[0]["title"], "Bohemian Rhapsody")


class AlbumArtistMigrationBackfillTests(unittest.TestCase):
    """A rescan skips any file whose mtime hasn't changed (scanner.run_scan),
    so tracks indexed before album_artist existed would never have that tag
    read for them otherwise. db.init_db() must zero every track's mtime the
    first time it adds the column (forcing exactly one full rescan), and
    never do it again on later startups."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "legacy.db")
        self.control_path = os.path.join(self.temp.name, "control.db")
        self._build_pre_album_artist_fixture()
        self.patches = [
            mock.patch.object(db, "DB_PATH", self.db_path),
            mock.patch.object(db, "CONTROL_DB_PATH", self.control_path),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _build_pre_album_artist_fixture(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, title TEXT,
                artist TEXT, album TEXT, genre TEXT, year INTEGER, track_no INTEGER,
                duration INTEGER, bitrate INTEGER, size INTEGER, cover_hash TEXT, bpm REAL,
                mtime REAL, play_count INTEGER NOT NULL DEFAULT 0,
                play_count_tag_dirty INTEGER NOT NULL DEFAULT 0, loved INTEGER NOT NULL DEFAULT 0,
                indexed_at REAL DEFAULT (unixepoch())
            );
            INSERT INTO tracks (id, path, title, mtime) VALUES (1, '/music/a.mp3', 'A', 1700000000.0);
        """)
        conn.commit()
        conn.close()

    def _mtime(self):
        with db.db() as conn:
            return conn.execute("SELECT mtime FROM tracks WHERE id=1").fetchone()["mtime"]

    def test_first_init_after_adding_the_column_zeroes_mtime_to_force_one_rescan(self):
        db.init_db()
        self.assertEqual(self._mtime(), 0)

    def test_second_init_does_not_re_trigger_the_backfill(self):
        db.init_db()
        with db.db() as conn:
            conn.execute("UPDATE tracks SET mtime=1234.5 WHERE id=1")
        db.init_db()
        self.assertEqual(self._mtime(), 1234.5)


if __name__ == "__main__":
    unittest.main()
