import os
import random
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby

from adolar import smart_shuffle


def track(track_id, artist, album, bpm=120, genre=""):
    return {
        "id": track_id,
        "artist": artist,
        "album": album,
        "bpm": bpm,
        "genre": genre,
    }


class SmartShuffleTests(unittest.TestCase):
    def test_concurrent_refills_share_one_cycle(self):
        rows = [track(i, f"Artist {i}", "Album") for i in range(1, 101)]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shuffle.db")
            with smart_shuffle.session_scope(None, "radio", path, "library") as (token, _):
                pass

            def refill():
                with smart_shuffle.session_scope(token, "radio", path, "library") as (_, state):
                    return smart_shuffle.select_tracks(rows, 50, state, 100, 100, 100)

            with ThreadPoolExecutor(max_workers=2) as executor:
                first, second = list(executor.map(lambda _: refill(), range(2)))
            self.assertEqual(len(first) + len(second), 100)
            self.assertFalse({row['id'] for row in first} & {row['id'] for row in second})

    def test_full_500_song_cycle_across_batches_and_duplicate_files(self):
        rows = [{**track(i, f"Artist {i}", "Album"), "title": f"Song {i}"}
                for i in range(1, 501)]
        rows.append({**rows[0], "id": 501, "album": "Compilation"})
        state = smart_shuffle.ShuffleState(context="radio")
        selected = []
        for _ in range(20):
            selected.extend(smart_shuffle.select_tracks(rows, 25, state, 501, 500, 500))
        self.assertEqual(len(selected), 500)
        self.assertEqual(len({row['title'] for row in selected}), 500)
        next_batch = smart_shuffle.select_tracks(rows, 25, state, 501, 500, 500)
        self.assertEqual(len(next_batch), 25)
        self.assertEqual(state.cycle, 2)

    def test_exhausted_sample_does_not_reset_cycle(self):
        state = smart_shuffle.ShuffleState(context="radio", track_history=[1])
        self.assertEqual(smart_shuffle.select_tracks([track(1, "A", "B")], 1,
                                                    state, 500, 50, 50), [])
        self.assertEqual(state.track_history, [1])

    def test_persisted_session_survives_process_cache_loss(self):
        rows = [track(i, f"A{i}", "B") for i in range(1, 11)]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shuffle.db")
            with smart_shuffle.session_scope(None, "radio", path, "library") as (token, state):
                first = smart_shuffle.select_tracks(rows, 5, state, 10, 10, 10)
            smart_shuffle._sessions.clear()
            with smart_shuffle.session_scope(token, "radio", path, "library") as (next_token, state):
                second = smart_shuffle.select_tracks(rows, 5, state, 10, 10, 10)
            self.assertEqual(token, next_token)
            self.assertFalse({row['id'] for row in first} & {row['id'] for row in second})

    def test_cooldown_windows_follow_specification(self):
        self.assertEqual(smart_shuffle.cooldown_windows(100, 20, 10), (80, 15, 7))
        self.assertEqual(smart_shuffle.cooldown_windows(3, 1, 1), (2, 0, 0))

    def test_bpm_penalty_boundaries(self):
        self.assertEqual(smart_shuffle.bpm_penalty(120, 125), 0)
        self.assertEqual(smart_shuffle.bpm_penalty(120, 140), 37.5)
        self.assertEqual(smart_shuffle.bpm_penalty(120, 160), 157.5)
        self.assertEqual(smart_shuffle.bpm_penalty(None, 160), 0)

    def test_track_cooldown_survives_multiple_batches(self):
        rows = [track(i, f"Artist {i}", f"Album {i}") for i in range(1, 21)]
        state = smart_shuffle.ShuffleState(context="test")
        first = smart_shuffle.select_tracks(
            rows, 5, state, 20, 20, 20, rng=random.Random(1)
        )
        second = smart_shuffle.select_tracks(
            rows, 5, state, 20, 20, 20, rng=random.Random(2)
        )
        self.assertFalse({row["id"] for row in first} & {row["id"] for row in second})

    def test_track_history_restarts_after_complete_cycle(self):
        rows = [track(1, "Artist", "Album")]
        state = smart_shuffle.ShuffleState(context="test")
        first = smart_shuffle.select_tracks(
            rows, 1, state, 1, 1, 1, rng=random.Random(10)
        )
        second = smart_shuffle.select_tracks(
            rows, 1, state, 1, 1, 1, rng=random.Random(11)
        )
        self.assertEqual([row["id"] for row in first], [1])
        self.assertEqual([row["id"] for row in second], [1])

    def test_artist_penalty_prevents_immediate_clustering(self):
        rows = [
            track(1, "A", "A1"), track(2, "A", "A2"),
            track(3, "A", "A3"), track(4, "B", "B1"),
            track(5, "C", "C1"), track(6, "D", "D1"),
            track(7, "E", "E1"), track(8, "F", "F1"),
            track(9, "G", "G1"), track(10, "H", "H1"),
        ]
        state = smart_shuffle.ShuffleState(context="test")
        selected = smart_shuffle.select_tracks(
            rows, 10, state, 10, 8, 10, rng=random.Random(3)
        )
        remaining = list(rows)
        recent = []
        for chosen in selected:
            alternatives = [row for row in remaining if row["artist"] not in recent[-2:]]
            if alternatives:
                self.assertNotIn(chosen["artist"], recent[-2:])
            remaining = [row for row in remaining if row["id"] != chosen["id"]]
            recent.append(chosen["artist"])

    def test_bpm_smoothing_prefers_close_tempo(self):
        state = smart_shuffle.ShuffleState(context="test", last_bpm=120)
        rows = [track(1, "A", "A", 160), track(2, "B", "B", 126)]
        selected = smart_shuffle.select_tracks(
            rows, 1, state, 2, 2, 2, rng=random.Random(4)
        )
        self.assertEqual(selected[0]["id"], 2)

    def test_missing_bpm_makes_the_following_transition_neutral(self):
        state = smart_shuffle.ShuffleState(context="test", last_bpm=120)
        selected = smart_shuffle.select_tracks(
            [track(1, "A", "A", None)], 1, state, 2, 2, 2,
            rng=random.Random(5),
        )
        self.assertEqual(selected[0]["id"], 1)
        self.assertIsNone(state.last_bpm)

    def test_genre_spacing_avoids_long_same_genre_runs(self):
        rows = [
            track(i, f"Metal Artist {i}", f"Metal Album {i}", genre="Metal")
            for i in range(1, 31)
        ] + [
            track(31, "Jazz Artist", "Jazz Album", genre="Jazz"),
            track(32, "Pop Artist", "Pop Album", genre="Pop"),
        ]
        state = smart_shuffle.ShuffleState(context="test")
        selected = smart_shuffle.select_tracks(
            rows, len(rows), state, len(rows), len(rows), len(rows),
            unique_genres=3, rng=random.Random(6),
        )
        genres = [row["genre"] for row in selected]
        longest_metal_run = max(
            sum(1 for _ in run)
            for genre, run in groupby(genres)
            if genre == "Metal"
        )
        self.assertLessEqual(longest_metal_run, 10)

    def test_genre_spacing_can_be_disabled_for_genre_filters(self):
        rows = [
            track(1, "A", "One", genre="Metal"),
            track(2, "B", "Two", genre="Jazz"),
        ]
        state = smart_shuffle.ShuffleState(context="test")
        state.last_genre = "metal"
        state.genre_run = 1
        state.sequence_index = 1
        selected = smart_shuffle.select_tracks(
            rows, 1, state, 2, 2, 2, unique_genres=2,
            use_genre_spacing=False, rng=random.Random(1),
        )
        self.assertEqual(selected[0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
