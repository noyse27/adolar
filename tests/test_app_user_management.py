import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-usermgmt-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-usermgmt-import-control.db"),
)

from adolar import application as app_module
from adolar import auth


class UserManagementTestBase(unittest.TestCase):
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
        self.client.set_cookie("adolar_session", "admin-token")
        self.login_patch = mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.admin_id), must_change_password=0),
        )
        self.login_patch.start()

    def tearDown(self):
        self.login_patch.stop()
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _as_user(self):
        return mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.user_id), must_change_password=0),
        )


class ListUsersTests(UserManagementTestBase):
    def test_admin_can_list_all_users(self):
        response = self.client.get("/api/users")
        self.assertEqual(response.status_code, 200)
        usernames = {u["username"] for u in response.get_json()}
        self.assertEqual(usernames, {"admin", "listener"})

    def test_non_admin_is_forbidden(self):
        with self._as_user():
            response = self.client.get("/api/users")
        self.assertEqual(response.status_code, 403)


class CreateUserTests(UserManagementTestBase):
    def test_creates_a_user_and_logs_audit(self):
        response = self.client.post("/api/users", json={"username": "newbie", "password": "password123"})
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(auth.get_user_by_name("newbie"))
        entries = app_module.db.get_audit_log()
        self.assertEqual(entries[0]["action"], "user.created")

    def test_rejects_missing_username(self):
        response = self.client.post("/api/users", json={"password": "password123"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_short_password(self):
        response = self.client.post("/api/users", json={"username": "x", "password": "short"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_duplicate_username(self):
        response = self.client.post("/api/users", json={"username": "listener", "password": "password123"})
        self.assertEqual(response.status_code, 409)


class DeleteUserTests(UserManagementTestBase):
    def test_admin_can_delete_another_user(self):
        response = self.client.delete(f"/api/users/{self.user_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(auth.get_user_by_id(self.user_id))

    def test_admin_cannot_delete_their_own_account(self):
        response = self.client.delete(f"/api/users/{self.admin_id}")
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(auth.get_user_by_id(self.admin_id))


class SetPasswordTests(UserManagementTestBase):
    def test_admin_reset_forces_a_password_change(self):
        response = self.client.post(
            f"/api/users/{self.user_id}/password", json={"password": "newpassword1"},
        )
        self.assertEqual(response.status_code, 200)
        user = auth.get_user_by_name("listener")
        self.assertTrue(auth.verify_password(user, "newpassword1"))
        self.assertEqual(user["must_change_password"], 1)

    def test_rejects_short_password(self):
        response = self.client.post(f"/api/users/{self.user_id}/password", json={"password": "short"})
        self.assertEqual(response.status_code, 400)


class CapabilityTests(UserManagementTestBase):
    def test_set_download_capability(self):
        response = self.client.post(f"/api/users/{self.user_id}/download", json={"allow": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth.get_user_by_id(self.user_id)["allow_download"], 1)

    def test_set_capability_rejects_unknown_capability_name(self):
        response = self.client.post(
            f"/api/users/{self.user_id}/capability/not-a-real-one", json={"allow": True},
        )
        self.assertEqual(response.status_code, 400)

    def test_set_capability_playlists(self):
        response = self.client.post(
            f"/api/users/{self.user_id}/capability/playlists", json={"allow": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth.get_user_by_id(self.user_id)["allow_playlists"], 0)

    def test_set_playcount_contribution(self):
        response = self.client.post(f"/api/users/{self.user_id}/playcount", json={"allow": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth.get_user_by_id(self.user_id)["contributes_playcount"], 1)


class SetActiveTests(UserManagementTestBase):
    def test_admin_can_deactivate_another_user(self):
        response = self.client.post(f"/api/users/{self.user_id}/active", json={"active": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth.get_user_by_id(self.user_id)["is_active"], 0)

    def test_deactivating_revokes_sessions(self):
        # get_user_by_token is mocked module-wide for this test class (always
        # "logged in as admin"), so check the underlying session row directly
        # instead of going through it.
        token = auth.create_session(self.user_id, remember=False)
        self.client.post(f"/api/users/{self.user_id}/active", json={"active": False})
        with app_module.db.db() as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE token=?", (token,)).fetchone()
        self.assertIsNone(row)

    def test_admin_cannot_deactivate_their_own_account(self):
        response = self.client.post(f"/api/users/{self.admin_id}/active", json={"active": False})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
