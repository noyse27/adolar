import os
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(_temp_dir.name, "adolar-test.db")

import app as app_module


def candidate(track_id, artist, album, bpm=120):
    return {
        "id": track_id,
        "path": f"track-{track_id}.mp3",
        "title": f"Track {track_id}",
        "artist": artist,
        "album": album,
        "genre": "Synthpop",
        "year": 1985,
        "track_no": track_id,
        "duration": 180,
        "duration_fmt": "3:00",
        "bitrate": 320,
        "size": 1,
        "cover_hash": None,
        "bpm": bpm,
        "format": "MP3",
        "has_cover": False,
        "loved": False,
        "user_play_count": 0,
        "last_played_at": None,
    }


class ShuffleApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "test-token")
        self.user = {
            "id": 7,
            "username": "tester",
            "role": "user",
            "allow_download": 0,
            "contributes_playcount": 0,
            "must_change_password": 0,
        }

    def test_search_filters_are_forwarded_to_smart_shuffle(self):
        rows = [
            candidate(1, "A", "One", 120),
            candidate(2, "B", "Two", 124),
            candidate(3, "C", "Three", 128),
        ]
        with mock.patch.object(app_module._auth, "get_user_by_token", return_value=self.user), \
             mock.patch.object(app_module.db, "search_tracks", return_value=(3, rows)) as search:
            response = self.client.get(
                "/api/shuffle?genre=Synthpop&decade=1980&count=2"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 2)
        self.assertTrue(response.headers.get("X-Shuffle-Session"))
        self.assertEqual(response.headers.get("X-Shuffle-Total"), "3")
        kwargs = search.call_args.kwargs
        self.assertEqual(kwargs["genre"], "Synthpop")
        self.assertEqual(kwargs["decade"], "1980")
        self.assertTrue(kwargs["random_order"])

    def test_changed_filters_reset_a_reused_shuffle_session(self):
        rows = [candidate(1, "A", "One"), candidate(2, "B", "Two")]
        with mock.patch.object(app_module._auth, "get_user_by_token", return_value=self.user), \
             mock.patch.object(app_module.db, "search_tracks", return_value=(2, rows)):
            first = self.client.get("/api/shuffle?genre=Synthpop&count=1")
            token = first.headers["X-Shuffle-Session"]
            second = self.client.get(
                f"/api/shuffle?genre=Darkwave&count=1&shuffle_session={token}"
            )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers["X-Shuffle-Session"], token)
        self.assertEqual(len(second.get_json()), 1)


if __name__ == "__main__":
    unittest.main()
