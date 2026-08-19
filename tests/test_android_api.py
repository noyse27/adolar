import os
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "android-test.db"))
os.environ.setdefault("CONTROL_DB_PATH", os.path.join(_temp_dir.name, "android-test-control.db"))

from adolar import adolar4u
from adolar import application as app_module
from adolar.routes import android as android_routes


class AndroidApiTests(unittest.TestCase):
    USER_ID = 31
    TRACK_ID = 601

    def setUp(self):
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password,
                     contributes_playcount)
                VALUES (?, 'android-listener', 'unused', 'user', 0, 1)
            """, (self.USER_ID,))
            conn.execute("""
                INSERT OR REPLACE INTO tracks
                    (id, path, title, artist, album, genre, duration)
                VALUES (?, 'android-test.mp3', 'Ping', 'Mobile Listener', 'Tests',
                        'Electronic', 200)
            """, (self.TRACK_ID,))
            conn.execute("DELETE FROM android_devices WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM android_track_links WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM android_event_receipts WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM user_play_counts WHERE user_id=?", (self.USER_ID,))
            conn.execute("UPDATE tracks SET play_count=0 WHERE id=?", (self.TRACK_ID,))
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        self.user = {
            "id": self.USER_ID,
            "username": "android-listener",
            "role": "user",
            "allow_download": 0,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 1,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.client = app_module.app.test_client()

    def _login(self, user=None):
        return mock.patch.object(
            app_module._auth, "get_user_by_token", return_value=user or self.user,
        )

    def _register_device(self) -> str:
        self.client.set_cookie("adolar_session", "android-test-token")
        with self._login():
            response = self.client.post(
                "/api/android/v1/register-device", json={"name": "Test-Handy"})
        self.assertEqual(response.status_code, 201)
        return response.get_json()["device_token"]

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def test_register_device_requires_login(self):
        response = self.client.post("/api/android/v1/register-device")
        self.assertEqual(response.status_code, 401)

    def test_registered_device_token_authenticates_sync_endpoints(self):
        token = self._register_device()
        response = self.client.post(
            "/api/android/v1/tracks/match", json={"tracks": []},
            headers=self._auth_headers(token),
        )
        self.assertEqual(response.status_code, 200)

    def test_events_batch_rejects_session_cookie_without_device_token(self):
        """Background sync must use a device token, never the session cookie."""
        self.client.set_cookie("adolar_session", "android-test-token")
        with self._login():
            response = self.client.post(
                "/api/android/v1/events/batch", json={"events": []})
        self.assertEqual(response.status_code, 401)

    def test_revoked_device_token_is_rejected(self):
        token = self._register_device()
        with app_module.db.db() as conn:
            device = conn.execute(
                "SELECT id FROM android_devices WHERE user_id=?", (self.USER_ID,)
            ).fetchone()
        app_module._auth.revoke_android_device_token(device["id"], self.USER_ID)
        response = self.client.post(
            "/api/android/v1/tracks/match", json={"tracks": []},
            headers=self._auth_headers(token),
        )
        self.assertEqual(response.status_code, 401)

    def test_match_track_resolves_unique_matched_ambiguous_and_unmatched(self):
        token = self._register_device()
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT INTO tracks (path, title, artist, album, duration)
                VALUES ('dup1.mp3', 'Echo', 'Duplicate Artist', 'A', 200)
            """)
            conn.execute("""
                INSERT INTO tracks (path, title, artist, album, duration)
                VALUES ('dup2.mp3', 'Echo', 'Duplicate Artist', 'B', 240)
            """)
        response = self.client.post("/api/android/v1/tracks/match", json={"tracks": [
            {"local_track_id": "1", "artist": "Mobile Listener", "title": "Ping"},
            {"local_track_id": "2", "artist": "Duplicate Artist", "title": "Echo"},
            {"local_track_id": "3", "artist": "Nobody", "title": "Nothing"},
        ]}, headers=self._auth_headers(token))
        self.assertEqual(response.status_code, 200)
        results = {row["local_track_id"]: row for row in response.get_json()["results"]}
        self.assertEqual(results["1"]["status"], "matched")
        self.assertEqual(results["1"]["track_id"], self.TRACK_ID)
        self.assertEqual(results["2"]["status"], "ambiguous")
        self.assertEqual(results["3"]["status"], "unmatched")

    def test_confirmed_match_is_cached_and_not_rederived(self):
        token = self._register_device()
        first = self.client.post("/api/android/v1/tracks/match", json={"tracks": [
            {"local_track_id": "1", "artist": "Mobile Listener", "title": "Ping"},
        ]}, headers=self._auth_headers(token)).get_json()["results"][0]
        self.assertEqual(first["status"], "matched")
        with app_module.db.db() as conn:
            # If the track were deleted, only a cached 'matched' row would
            # still resolve it -- proves the cache short-circuits re-derivation.
            conn.execute("DELETE FROM tracks WHERE id=?", (self.TRACK_ID,))
            self.assertEqual(conn.execute(
                "SELECT match_kind FROM android_track_links WHERE local_track_id='1'"
            ).fetchone()["match_kind"], "matched")

    def test_events_batch_is_idempotent_on_duplicate_event_id(self):
        token = self._register_device()
        event = {
            "event_id": "evt-1:completed", "event_type": "completed",
            "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
            "album": "Tests", "position_seconds": 200, "duration_seconds": 200,
            "started_at": 1700000000, "playcount_eligible": True,
            "scrobble_eligible": False, "source": "android_local",
        }
        first = self.client.post(
            "/api/android/v1/events/batch", json={"events": [event]},
            headers=self._auth_headers(token),
        )
        second = self.client.post(
            "/api/android/v1/events/batch", json={"events": [event]},
            headers=self._auth_headers(token),
        )
        self.assertEqual(first.get_json()["results"][0]["status"], "applied")
        self.assertEqual(second.get_json()["results"][0]["status"], "duplicate")
        with app_module.db.db() as conn:
            count = conn.execute(
                "SELECT count FROM user_play_counts WHERE user_id=? AND track_id=?",
                (self.USER_ID, self.TRACK_ID),
            ).fetchone()["count"]
        self.assertEqual(count, 1)

    def test_playcount_only_credited_when_eligible(self):
        token = self._register_device()
        event = {
            "event_id": "evt-2:skipped", "event_type": "skipped",
            "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
            "position_seconds": 5, "duration_seconds": 200,
            "started_at": 1700000000, "playcount_eligible": False,
            "scrobble_eligible": False, "source": "android_local",
        }
        self.client.post(
            "/api/android/v1/events/batch", json={"events": [event]},
            headers=self._auth_headers(token),
        )
        with app_module.db.db() as conn:
            row = conn.execute(
                "SELECT count FROM user_play_counts WHERE user_id=? AND track_id=?",
                (self.USER_ID, self.TRACK_ID),
            ).fetchone()
        self.assertIsNone(row)

    def test_events_batch_forwards_all_event_types_to_adolar4u(self):
        token = self._register_device()
        for kind in ("started", "skipped", "completed"):
            self.client.post("/api/android/v1/events/batch", json={"events": [{
                "event_id": f"evt-{kind}", "event_type": kind,
                "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
                "position_seconds": 1, "duration_seconds": 200,
                "started_at": 1700000000, "playcount_eligible": False,
                "scrobble_eligible": False, "source": "android_local",
            }]}, headers=self._auth_headers(token))
        with app_module.db.db() as conn:
            rows = conn.execute(
                "SELECT event_type, source FROM adolar4u_listening_events "
                "WHERE user_id=? ORDER BY event_type", (self.USER_ID,)
            ).fetchall()
        self.assertEqual(
            sorted(r["event_type"] for r in rows), ["completed", "skipped", "started"])
        self.assertTrue(all(r["source"] == "android_local" for r in rows))

    def test_events_batch_scrobbles_with_original_started_at(self):
        token = self._register_device()
        app_module.db.set_lastfm_account(self.USER_ID, "listener", "session-key")
        with mock.patch.object(android_routes.android, "_submit_lastfm_call") as submit:
            self.client.post("/api/android/v1/events/batch", json={"events": [{
                "event_id": "evt-scrobble", "event_type": "completed",
                "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
                "position_seconds": 200, "duration_seconds": 200,
                "started_at": 1700000000, "playcount_eligible": True,
                "scrobble_eligible": True, "source": "android_local",
            }]}, headers=self._auth_headers(token))
        submit.assert_called_once()
        args, kwargs = submit.call_args
        self.assertEqual(args[1], android_routes.android.lastfm.scrobble)
        self.assertEqual(args[2], "session-key")
        self.assertEqual(args[3:5], ("Mobile Listener", "Ping"))
        self.assertEqual(kwargs["timestamp"], 1700000000)

    def test_loved_event_sets_adolar_favorite(self):
        token = self._register_device()
        response = self.client.post("/api/android/v1/events/batch", json={"events": [{
            "event_id": "evt-love-1", "event_type": "loved",
            "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
        }]}, headers=self._auth_headers(token))
        self.assertEqual(response.get_json()["results"][0]["status"], "applied")
        self.assertIn(self.TRACK_ID, app_module.db.get_favorite_track_ids(self.USER_ID))

    def test_unloved_event_clears_adolar_favorite(self):
        token = self._register_device()
        app_module.db.set_favorite(self.USER_ID, self.TRACK_ID, True)
        response = self.client.post("/api/android/v1/events/batch", json={"events": [{
            "event_id": "evt-unlove-1", "event_type": "unloved",
            "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
        }]}, headers=self._auth_headers(token))
        self.assertEqual(response.get_json()["results"][0]["status"], "applied")
        self.assertNotIn(
            self.TRACK_ID, app_module.db.get_favorite_track_ids(self.USER_ID))

    def test_loved_event_mirrors_to_lastfm_when_auto_love_enabled(self):
        token = self._register_device()
        app_module.db.set_lastfm_account(self.USER_ID, "listener", "session-key")
        with mock.patch.object(android_routes.android.favorites.lastfm, "love") as love:
            self.client.post("/api/android/v1/events/batch", json={"events": [{
                "event_id": "evt-love-2", "event_type": "loved",
                "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
            }]}, headers=self._auth_headers(token))
        love.assert_called_once_with("session-key", "Mobile Listener", "Ping")

    def test_loved_event_does_not_create_a_listening_event(self):
        token = self._register_device()
        self.client.post("/api/android/v1/events/batch", json={"events": [{
            "event_id": "evt-love-3", "event_type": "loved",
            "local_track_id": "1", "artist": "Mobile Listener", "title": "Ping",
        }]}, headers=self._auth_headers(token))
        with app_module.db.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM adolar4u_listening_events WHERE user_id=?",
                (self.USER_ID,),
            ).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_events_batch_rejects_oversized_batch(self):
        token = self._register_device()
        events = [{
            "event_id": f"evt-{i}", "event_type": "started",
            "local_track_id": str(i), "artist": "A", "title": "T",
        } for i in range(201)]
        response = self.client.post(
            "/api/android/v1/events/batch", json={"events": events},
            headers=self._auth_headers(token),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximal 200", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
