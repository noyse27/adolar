import os
import tempfile
import unittest
from unittest import mock


_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar4u-test.db"))

import adolar4u
import app as app_module


class Adolar4UTests(unittest.TestCase):
    USER_ID = 21
    TRACK_ID = 401

    def setUp(self):
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (?, 'a4u-listener', 'unused', 'user', 0)
            """, (self.USER_ID,))
            conn.execute("""
                INSERT OR IGNORE INTO tracks (id, path, title, artist, album, genre)
                VALUES (?, 'a4u-test.mp3', 'Signal', 'Listener', 'Tests', 'Electronic')
            """, (self.TRACK_ID,))
            conn.execute("DELETE FROM adolar4u_listening_events WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM adolar4u_user_settings WHERE user_id=?", (self.USER_ID,))
        adolar4u.update_global_settings({
            "enabled": False,
            "audio_analysis": False,
            "collaborative": False,
        })
        self.user = {
            "id": self.USER_ID,
            "username": "a4u-listener",
            "role": "user",
            "allow_download": 0,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "adolar4u-test-token")

    def _login(self, user=None):
        return mock.patch.object(
            app_module._auth, "get_user_by_token", return_value=user or self.user,
        )

    def test_event_collection_requires_global_and_personal_opt_in(self):
        with self._login():
            disabled = self.client.post(
                f"/api/adolar4u/events/{self.TRACK_ID}",
                json={"event_type": "started"},
            )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.get_json()["reason"], "module_disabled")

        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        with self._login():
            accepted = self.client.post(
                f"/api/adolar4u/events/{self.TRACK_ID}",
                json={
                    "event_type": "skipped",
                    "position_seconds": 12,
                    "duration_seconds": 240,
                    "source": "radio",
                    "reason": "manual_next",
                    "client_event_id": "skip-1",
                },
            )
        self.assertEqual(accepted.status_code, 202)
        self.assertTrue(accepted.get_json()["accepted"])
        with app_module.db.db() as conn:
            event = conn.execute("""
                SELECT event_type, completion_ratio, source, reason
                FROM adolar4u_listening_events WHERE user_id=?
            """, (self.USER_ID,)).fetchone()
        self.assertEqual(event["event_type"], "skipped")
        self.assertAlmostEqual(event["completion_ratio"], 0.05)
        self.assertEqual(event["source"], "radio")
        self.assertEqual(event["reason"], "manual_next")

    def test_learning_pause_stops_collection_without_disabling_profile(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "learning_paused": True,
        })
        result = adolar4u.record_event(
            self.USER_ID, self.TRACK_ID, {"event_type": "started"},
        )
        self.assertEqual(result["reason"], "learning_paused")

    def test_duplicate_client_event_is_idempotent(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        event = {"event_type": "completed", "client_event_id": "complete-1"}
        self.assertTrue(adolar4u.record_event(self.USER_ID, self.TRACK_ID, event)["accepted"])
        duplicate = adolar4u.record_event(self.USER_ID, self.TRACK_ID, event)
        self.assertFalse(duplicate["accepted"])
        self.assertTrue(duplicate["duplicate"])

    def test_user_can_delete_personal_learning_history(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        adolar4u.record_event(
            self.USER_ID, self.TRACK_ID, {"event_type": "started"},
        )
        with self._login():
            response = self.client.delete("/api/adolar4u/profile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_events"], 1)

    def test_global_settings_require_admin(self):
        with self._login():
            denied = self.client.put(
                "/api/admin/adolar4u/settings", json={"enabled": True},
            )
        self.assertEqual(denied.status_code, 403)

        admin = {**self.user, "role": "admin"}
        with self._login(admin):
            allowed = self.client.put(
                "/api/admin/adolar4u/settings", json={"enabled": True},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.get_json()["enabled"])


if __name__ == "__main__":
    unittest.main()
