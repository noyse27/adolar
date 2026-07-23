import os
import tempfile
import time
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar-monitor-test.db"))

import app as app_module


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.db.init_db()
        cls.user_id = app_module._auth.create_user("monitor-admin", "password123", role="admin")
        with app_module.db.db() as conn:
            conn.execute(
                "UPDATE users SET must_change_password=0 WHERE id=?", (cls.user_id,)
            )

    def setUp(self):
        self.client = app_module.app.test_client()
        with app_module.db.db() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM connection_log")

    def test_monitor_requires_admin(self):
        response = self.client.get("/api/admin/monitor")
        self.assertEqual(response.status_code, 401)

    def test_login_is_recorded_and_ip_is_masked(self):
        token = app_module._auth.create_session(
            self.user_id,
            remember=False,
            product="android",
            ip_address="192.168.10.42",
        )
        self.client.set_cookie(app_module._auth.SESSION_COOKIE, token)

        memory = mock.Mock(percent=37.5, used=4 * 1024**3, total=8 * 1024**3)
        with mock.patch.object(app_module.psutil, "virtual_memory", return_value=memory), \
             mock.patch.object(app_module.psutil, "cpu_percent", return_value=12.5), \
             mock.patch.object(app_module.psutil, "cpu_count", return_value=4), \
             mock.patch.object(app_module.psutil, "boot_time", return_value=time.time() - 60):
            response = self.client.get("/api/admin/monitor")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["system"]["cpu_percent"], 12.5)
        self.assertEqual(len(payload["current_connections"]), 1)
        connection = payload["current_connections"][0]
        self.assertEqual(connection["username"], "monitor-admin")
        self.assertEqual(connection["product"], "android")
        self.assertEqual(connection["ip_address"], "192.xxx.xxx.42")
        self.assertNotIn("192.168.10.42", response.get_data(as_text=True))

    def test_only_ten_recent_connections_are_returned(self):
        now = time.time()
        with app_module.db.db() as conn:
            for index in range(12):
                conn.execute(
                    """INSERT INTO connection_log
                           (user_id, username, product, ip_address, connected_at, last_seen_at)
                       VALUES (?,?,?,?,?,?)""",
                    (self.user_id, f"user-{index}", "adolar_web", "10.0.0.1", now + index, now + index),
                )
        current, recent = app_module._monitor_connections()
        self.assertEqual(current, [])
        self.assertEqual(len(recent), 10)
        self.assertEqual(recent[0]["username"], "user-11")

    def test_public_heartbeat_is_tracked_as_guest(self):
        response = self.client.post("/api/client/heartbeat", json={
            "product": "companion",
            "client_id": "public-companion-test",
        })
        self.assertEqual(response.status_code, 200)
        current, _ = app_module._monitor_connections()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["username"], "Gast")
        self.assertEqual(current[0]["product"], "companion")

    def test_heartbeat_backfills_old_authenticated_session(self):
        token = "old-session-without-connection"
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                (token, self.user_id, time.time() + 600),
            )
        self.client.set_cookie(app_module._auth.SESSION_COOKIE, token)
        response = self.client.post("/api/client/heartbeat", json={
            "product": "adolar_web",
            "client_id": "old-web-session-test",
        })
        self.assertEqual(response.status_code, 200)
        with app_module.db.db() as conn:
            row = conn.execute("""
                SELECT s.connection_id, c.username, c.product
                FROM sessions s JOIN connection_log c ON c.id=s.connection_id
                WHERE s.token=?
            """, (token,)).fetchone()
        self.assertIsNotNone(row["connection_id"])
        self.assertEqual(row["username"], "monitor-admin")
        self.assertEqual(row["product"], "adolar_web")


if __name__ == "__main__":
    unittest.main()
