import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-random-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-random-import-control.db"),
)

import db


class GetRandomTracksTests(unittest.TestCase):
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
            for i in range(10):
                conn.execute(
                    "INSERT INTO tracks (path, title, artist, album, genre) VALUES (?,?,?,?,?)",
                    (f"/music/{i}.mp3", f"Track {i}", f"Artist {i % 3}", f"Album {i % 4}", "Rock"),
                )

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_returns_the_requested_count(self):
        tracks = db.get_random_tracks(count=5)
        self.assertEqual(len(tracks), 5)

    def test_count_is_clamped_to_the_available_pool(self):
        tracks = db.get_random_tracks(count=1000)
        self.assertEqual(len(tracks), 10)

    def test_count_is_clamped_to_at_least_one(self):
        tracks = db.get_random_tracks(count=0)
        self.assertEqual(len(tracks), 1)

    def test_excluded_ids_are_never_returned(self):
        first_batch = db.get_random_tracks(count=10)
        excluded_ids = [t["id"] for t in first_batch[:5]]
        second_batch = db.get_random_tracks(count=10, exclude_ids=excluded_ids)
        returned_ids = {t["id"] for t in second_batch}
        self.assertTrue(returned_ids.isdisjoint(excluded_ids))

    def test_shuffle_state_total_tracks_gets_populated_on_first_call(self):
        import smart_shuffle
        state = smart_shuffle.ShuffleState(context="random")
        self.assertIsNone(state.total_tracks)
        db.get_random_tracks(count=3, shuffle_state=state)
        self.assertEqual(state.total_tracks, 10)
        self.assertEqual(state.unique_artists, 3)

    def test_reusing_a_shuffle_state_does_not_repeat_stats_query(self):
        import smart_shuffle
        state = smart_shuffle.ShuffleState(
            context="random", total_tracks=999, unique_artists=999,
            unique_albums=999, unique_genres=999,
        )
        # If get_random_tracks trusted a pre-populated total_tracks, the pool
        # sizing would be based on 999, not the real 10-row table — but the
        # result set should still just be bounded by what actually exists.
        tracks = db.get_random_tracks(count=5, shuffle_state=state)
        self.assertLessEqual(len(tracks), 10)
        self.assertEqual(state.total_tracks, 999)  # left untouched, as documented


if __name__ == "__main__":
    unittest.main()
