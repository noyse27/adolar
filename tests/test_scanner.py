import os
import tempfile
import time
import unittest
from unittest import mock

from mutagen.id3 import APIC, ID3, PCNT, TBPM, TIT2, TPE1, TPE2, TXXX

import db
import scanner


def _make_mp3(path: str, **tags) -> None:
    """Write a minimal but real, decodable MP3 file with optional ID3 tags.

    A single MPEG1 Layer III frame (128kbps/44100Hz/mono) repeated a few
    times is enough for mutagen to report real duration/bitrate info, so
    scanner._scan_file exercises its actual tag-reading code against a
    real file instead of a mock.
    """
    header = bytes([0xFF, 0xFB, 0x90, 0xC4])
    frame_size = 144 * 128000 // 44100
    frame = header + bytes(frame_size - len(header))
    with open(path, "wb") as f:
        # ~0.026s per frame; enough repeats that the truncated-to-int
        # duration scanner.py reports is not rounded down to 0.
        for _ in range(50):
            f.write(frame)

    id3_map = {
        "title": lambda v: TIT2(encoding=3, text=v),
        "artist": lambda v: TPE1(encoding=3, text=v),
        "album_artist": lambda v: TPE2(encoding=3, text=v),
        "bpm": lambda v: TBPM(encoding=3, text=str(v)),
        "play_count": lambda v: PCNT(count=v),
        "loved": lambda v: TXXX(encoding=3, desc="LOVE RATING", text="L" if v else ""),
        "cover": lambda v: APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=v),
    }
    if tags:
        id3 = ID3()
        for key, value in tags.items():
            frame_obj = id3_map[key](value)
            id3[frame_obj.HashKey] = frame_obj
        id3.save(path)


class ScanFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "track.mp3")

    def tearDown(self):
        self.temp.cleanup()

    def test_extracts_core_tags_and_technical_info(self):
        _make_mp3(self.path, title="Get Lucky", artist="Daft Punk")
        with mock.patch.object(scanner, "save_cover"):
            data = scanner._scan_file(self.path)
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "Get Lucky")
        self.assertEqual(data["artist"], "Daft Punk")
        self.assertEqual(data["path"], self.path)
        self.assertGreater(data["duration"], 0)
        self.assertEqual(data["bitrate"], 128)
        self.assertGreater(data["size"], 0)
        self.assertIsNone(data["cover_hash"])
        self.assertIsNone(data["bpm"])
        self.assertEqual(data["play_count"], 0)
        self.assertFalse(data["loved"])

    def test_reads_bpm_from_tbpm_tag(self):
        _make_mp3(self.path, bpm=128)
        data = scanner._scan_file(self.path)
        self.assertEqual(data["bpm"], 128.0)

    def test_reads_play_count_from_pcnt_tag(self):
        _make_mp3(self.path, play_count=7)
        data = scanner._scan_file(self.path)
        self.assertEqual(data["play_count"], 7)

    def test_reads_loved_flag_from_txxx_love_rating(self):
        _make_mp3(self.path, loved=True)
        data = scanner._scan_file(self.path)
        self.assertTrue(data["loved"])

    def test_not_loved_when_love_rating_tag_absent(self):
        _make_mp3(self.path)
        data = scanner._scan_file(self.path)
        self.assertFalse(data["loved"])

    def test_reads_album_artist_from_tpe2_tag_distinct_from_artist(self):
        # TPE2 (album artist) is what a compilation tags "Various Artists"
        # on, while TPE1 (artist) stays the individual track's performer —
        # search_albums() relies on these being kept separate.
        _make_mp3(self.path, artist="In Strict Confidence", album_artist="Various Artists")
        data = scanner._scan_file(self.path)
        self.assertEqual(data["artist"], "In Strict Confidence")
        self.assertEqual(data["album_artist"], "Various Artists")

    def test_album_artist_is_none_when_tag_absent(self):
        _make_mp3(self.path, artist="Daft Punk")
        data = scanner._scan_file(self.path)
        self.assertIsNone(data["album_artist"])

    def test_extracts_embedded_cover_art_and_saves_it(self):
        _make_mp3(self.path, cover=b"\x89PNGfakecoverbytes")
        with mock.patch.object(scanner, "save_cover") as mocked_save:
            data = scanner._scan_file(self.path)
        self.assertIsNotNone(data["cover_hash"])
        mocked_save.assert_called_once()
        saved_hash, saved_data, saved_mime = mocked_save.call_args[0]
        self.assertEqual(saved_hash, data["cover_hash"])
        self.assertEqual(saved_data, b"\x89PNGfakecoverbytes")
        self.assertEqual(saved_mime, "image/png")

    def test_returns_none_and_does_not_raise_for_unreadable_file(self):
        with open(self.path, "wb") as f:
            f.write(b"not actually an mp3")
        self.assertIsNone(scanner._scan_file(self.path))

    def test_returns_none_for_missing_file(self):
        self.assertIsNone(scanner._scan_file(os.path.join(self.temp.name, "missing.mp3")))


class CollectMp3sTests(unittest.TestCase):
    def test_finds_supported_extensions_recursively_and_ignores_others(self):
        with tempfile.TemporaryDirectory() as root:
            wanted = [
                "a.mp3", "b.flac", "c.m4a", "d.ogg", "e.opus", "f.aac", "g.wav",
            ]
            for name in wanted:
                open(os.path.join(root, name), "wb").close()
            subdir = os.path.join(root, "sub")
            os.makedirs(subdir)
            open(os.path.join(subdir, "h.mp3"), "wb").close()
            open(os.path.join(root, "cover.jpg"), "wb").close()
            open(os.path.join(root, "notes.txt"), "wb").close()

            found = {os.path.basename(p) for p in scanner._collect_mp3s(root)}
        self.assertEqual(found, set(wanted) | {"h.mp3"})
        self.assertNotIn("cover.jpg", found)
        self.assertNotIn("notes.txt", found)


class BpmAndLoveTagRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "track.mp3")
        _make_mp3(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_bpm_tag_round_trips_through_read_bpm_tag(self):
        scanner._write_bpm_tag(self.path, 123.4)
        self.assertEqual(scanner._read_bpm_tag(self.path), 123.0)

    def test_read_bpm_tag_returns_none_when_absent(self):
        self.assertIsNone(scanner._read_bpm_tag(self.path))

    def test_write_love_tag_true_then_read_love_tag_reflects_it(self):
        self.assertIsNone(scanner.read_love_tag(self.path))
        scanner.write_love_tag(self.path, True)
        self.assertTrue(scanner.read_love_tag(self.path))

    def test_write_love_tag_false_after_true_clears_it(self):
        scanner.write_love_tag(self.path, True)
        self.assertTrue(scanner.read_love_tag(self.path))
        scanner.write_love_tag(self.path, False)
        self.assertFalse(scanner.read_love_tag(self.path))

    def test_write_love_tag_is_a_no_op_when_already_matching(self):
        scanner.write_love_tag(self.path, True)
        mtime_before = os.stat(self.path).st_mtime_ns
        scanner.write_love_tag(self.path, True)
        self.assertEqual(os.stat(self.path).st_mtime_ns, mtime_before)


class RunScanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music_root = os.path.join(self.temp.name, "music")
        os.makedirs(self.music_root)
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
            # Skip the real post-scan BPM/thumbnail background jobs: they pull in
            # librosa/PIL/app.py, which is unrelated to whether run_scan indexed
            # the files correctly.
            mock.patch.object(scanner, "run_bpm_scan"),
            mock.patch.object(scanner, "run_thumb_generation"),
        ]
        for p in self.patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _wait_for_scan_to_finish(self, timeout=5):
        deadline = time.time() + timeout
        while scanner.status()["running"]:
            if time.time() > deadline:
                self.fail("Scan did not finish in time")
            time.sleep(0.05)

    def _tracks(self):
        with db.db() as conn:
            return {
                row["path"]: dict(row)
                for row in conn.execute("SELECT * FROM tracks").fetchall()
            }

    def test_indexes_new_files_and_reports_them_in_the_database(self):
        _make_mp3(os.path.join(self.music_root, "one.mp3"), title="One", artist="Artist A")
        _make_mp3(os.path.join(self.music_root, "two.mp3"), title="Two", artist="Artist B")

        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()

        tracks = self._tracks()
        self.assertEqual(len(tracks), 2)
        titles = {row["title"] for row in tracks.values()}
        self.assertEqual(titles, {"One", "Two"})

    def test_run_scan_populates_album_artist_from_tag(self):
        _make_mp3(
            os.path.join(self.music_root, "one.mp3"),
            title="Enjoy the Silence", artist="In Strict Confidence",
            album_artist="Various Artists",
        )
        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()

        row = next(iter(self._tracks().values()))
        self.assertEqual(row["artist"], "In Strict Confidence")
        self.assertEqual(row["album_artist"], "Various Artists")

    def test_rescan_skips_unchanged_files_and_does_not_duplicate_rows(self):
        path = os.path.join(self.music_root, "one.mp3")
        _make_mp3(path, title="One")

        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()
        self.assertEqual(len(self._tracks()), 1)

        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()

        self.assertEqual(scanner.status()["skipped"], 1)
        self.assertEqual(len(self._tracks()), 1)

    def test_rescan_after_tag_change_updates_existing_row(self):
        path = os.path.join(self.music_root, "one.mp3")
        _make_mp3(path, title="Old Title")
        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()

        # Bump mtime so the scanner treats it as changed, like re-tagging would.
        _make_mp3(path, title="New Title")
        os.utime(path, (time.time() + 5, time.time() + 5))

        scanner.run_scan(self.music_root)
        self._wait_for_scan_to_finish()

        tracks = self._tracks()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[path]["title"], "New Title")

    def test_run_scan_is_a_no_op_while_already_running(self):
        sentinel = 12345.0
        scanner._update(running=True, started_at=sentinel)
        try:
            scanner.run_scan(self.music_root)
            # A real run would immediately overwrite started_at with time.time();
            # the sentinel surviving proves the guard clause returned early
            # instead of spawning a second worker.
            self.assertEqual(scanner._status["started_at"], sentinel)
        finally:
            scanner._update(running=False)


if __name__ == "__main__":
    unittest.main()
