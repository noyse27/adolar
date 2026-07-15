import random
import unittest

import smart_shuffle


def track(track_id, artist, album, bpm=120):
    return {
        "id": track_id,
        "artist": artist,
        "album": album,
        "bpm": bpm,
    }


class SmartShuffleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
