import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-adminmisc-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-adminmisc-import-control.db"),
)

import app as app_module
import auth


class AdminMiscTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.user_id = auth.create_user("listener", "password123", role="user")
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "token")
        self.login_patch = mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.admin_id), must_change_password=0),
        )
        self.login_patch.start()

    def tearDown(self):
        self.login_patch.stop()
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()

    def _as_user(self):
        return mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.user_id), must_change_password=0),
        )


class BlockedIpsRouteTests(AdminMiscTestBase):
    def test_requires_admin(self):
        with self._as_user():
            response = self.client.get("/api/admin/blocked-ips")
        self.assertEqual(response.status_code, 403)

    def test_lists_currently_blocked_ips(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("9.9.9.9")
        with mock.patch.object(auth.time, "time", return_value=1005.0):
            response = self.client.get("/api/admin/blocked-ips")
        self.assertEqual(response.status_code, 200)
        ips = {row["ip"] for row in response.get_json()}
        self.assertIn("9.9.9.9", ips)

    def test_unblock_clears_a_block(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("9.9.9.9")
        response = self.client.delete("/api/admin/blocked-ips/9.9.9.9")
        self.assertEqual(response.status_code, 200)
        blocked, _ = auth._bf_check("9.9.9.9")
        self.assertFalse(blocked)

    def test_unblock_requires_admin(self):
        with self._as_user():
            response = self.client.delete("/api/admin/blocked-ips/9.9.9.9")
        self.assertEqual(response.status_code, 403)


class AccessSettingsRouteTests(AdminMiscTestBase):
    def test_get_returns_defaults_when_unset(self):
        response = self.client.get("/api/admin/access-settings")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["allow_anonymous_web"], "0")
        self.assertEqual(data["companion_access"], "public")

    def test_get_requires_admin(self):
        with self._as_user():
            response = self.client.get("/api/admin/access-settings")
        self.assertEqual(response.status_code, 403)

    def test_put_updates_boolean_settings(self):
        response = self.client.put("/api/admin/access-settings", json={
            "allow_anonymous_web": True, "allow_user_playlists": False,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["allow_anonymous_web"], "1")
        self.assertEqual(data["allow_user_playlists"], "0")

    def test_put_rejects_invalid_companion_access_value(self):
        response = self.client.put(
            "/api/admin/access-settings", json={"companion_access": "not-a-real-mode"},
        )
        self.assertEqual(response.status_code, 400)

    def test_put_accepts_valid_companion_access_value(self):
        response = self.client.put(
            "/api/admin/access-settings", json={"companion_access": "disabled"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["companion_access"], "disabled")

    def test_put_logs_an_audit_entry(self):
        self.client.put("/api/admin/access-settings", json={"allow_anonymous_web": True})
        entries = app_module.db.get_audit_log()
        self.assertEqual(entries[0]["action"], "access.settings_updated")


class AuditLogRouteTests(AdminMiscTestBase):
    def test_requires_admin(self):
        with self._as_user():
            response = self.client.get("/api/admin/audit-log")
        self.assertEqual(response.status_code, 403)

    def test_returns_logged_entries_newest_first(self):
        app_module.db.log_audit(self.admin_id, "first", "", "")
        app_module.db.log_audit(self.admin_id, "second", "", "")
        response = self.client.get("/api/admin/audit-log")
        self.assertEqual(response.status_code, 200)
        actions = [e["action"] for e in response.get_json()]
        self.assertEqual(actions, ["second", "first"])

    def test_limit_query_param_is_respected(self):
        for i in range(5):
            app_module.db.log_audit(self.admin_id, f"action-{i}", "", "")
        response = self.client.get("/api/admin/audit-log?limit=2")
        self.assertEqual(len(response.get_json()), 2)


if __name__ == "__main__":
    unittest.main()
