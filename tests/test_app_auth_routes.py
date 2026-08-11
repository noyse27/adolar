import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-authroutes-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-authroutes-import-control.db"),
)

from adolar import application as app_module
from adolar import auth


class AuthRouteTestBase(unittest.TestCase):
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
        auth._bf_state.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()

    def _create_user(self, username, password, role="user", is_active=1, must_change=0):
        user_id = auth.create_user(username, password, role=role)
        with app_module.db.db() as conn:
            conn.execute(
                "UPDATE users SET is_active=?, must_change_password=? WHERE id=?",
                (is_active, must_change, user_id),
            )
        return user_id


class SetupRouteTests(AuthRouteTestBase):
    def test_get_setup_shows_form_when_no_users_exist(self):
        response = self.client.get("/setup")
        self.assertEqual(response.status_code, 200)

    def test_get_setup_redirects_to_login_once_a_user_exists(self):
        self._create_user("admin", "password123", role="admin")
        response = self.client.get("/setup")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_post_setup_rejects_short_password(self):
        response = self.client.post("/setup", data={
            "username": "admin", "password": "short", "password2": "short",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("mindestens 8 Zeichen", response.get_data(as_text=True))
        self.assertEqual(auth.user_count(), 0)

    def test_post_setup_rejects_mismatched_passwords(self):
        response = self.client.post("/setup", data={
            "username": "admin", "password": "password123", "password2": "different123",
        })
        self.assertIn("stimmen nicht", response.get_data(as_text=True))
        self.assertEqual(auth.user_count(), 0)

    def test_post_setup_rejects_empty_username(self):
        response = self.client.post("/setup", data={
            "username": "", "password": "password123", "password2": "password123",
        })
        self.assertIn("Benutzername", response.get_data(as_text=True))

    def test_post_setup_creates_admin_who_does_not_need_to_change_password(self):
        response = self.client.post("/setup", data={
            "username": "admin", "password": "password123", "password2": "password123",
        })
        self.assertEqual(response.status_code, 302)
        user = auth.get_user_by_name("admin")
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["must_change_password"], 0)
        self.assertIn(auth.SESSION_COOKIE, response.headers.get("Set-Cookie", ""))

    def test_post_setup_is_a_no_op_once_a_user_already_exists(self):
        self._create_user("admin", "password123", role="admin")
        response = self.client.post("/setup", data={
            "username": "attacker", "password": "password123", "password2": "password123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(auth.get_user_by_name("attacker"))


class LoginRouteTests(AuthRouteTestBase):
    def setUp(self):
        super().setUp()
        self._create_user("alice", "correct-password")

    def test_get_login_redirects_to_setup_when_no_users_exist(self):
        with app_module.db.db() as conn:
            conn.execute("DELETE FROM users")
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/setup", response.location)

    def test_wrong_password_returns_401_and_records_a_failure(self):
        response = self.client.post("/login", data={"username": "alice", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        blocked, _ = auth._bf_check("127.0.0.1")
        self.assertFalse(blocked)  # single failure shouldn't block yet

    def test_repeated_failures_trigger_a_block_and_429(self):
        for _ in range(auth.BF_SOFT_LIMIT):
            self.client.post("/login", data={"username": "alice", "password": "wrong"})
        response = self.client.post("/login", data={"username": "alice", "password": "correct-password"})
        self.assertEqual(response.status_code, 429)

    def test_correct_login_sets_session_cookie_and_redirects(self):
        response = self.client.post("/login", data={"username": "alice", "password": "correct-password"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(auth.SESSION_COOKIE, response.headers.get("Set-Cookie", ""))

    def test_successful_login_clears_prior_brute_force_failures(self):
        self.client.post("/login", data={"username": "alice", "password": "wrong"})
        self.client.post("/login", data={"username": "alice", "password": "correct-password"})
        blocked, _ = auth._bf_check("127.0.0.1")
        self.assertFalse(blocked)

    def test_inactive_user_cannot_log_in(self):
        self._create_user("bob", "password123", is_active=0)
        response = self.client.post("/login", data={"username": "bob", "password": "password123"})
        self.assertEqual(response.status_code, 401)

    def test_next_param_redirect_target_is_neutralized_if_external(self):
        response = self.client.post("/login", data={
            "username": "alice", "password": "correct-password", "next": "https://evil.example/",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")


class LogoutRouteTests(AuthRouteTestBase):
    def test_logout_deletes_the_session_and_clears_the_cookie(self):
        self._create_user("alice", "password123")
        self.client.post("/login", data={"username": "alice", "password": "password123"})
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)
        # Session should now be dead: /api/me must reject it.
        self.assertEqual(self.client.get("/api/me").status_code, 401)


class RadioLoginRouteTests(AuthRouteTestBase):
    def test_setup_required_when_no_users_exist(self):
        response = self.client.post("/api/radio/login", json={"username": "x", "password": "y"})
        self.assertEqual(response.status_code, 409)

    def test_invalid_credentials_returns_401(self):
        self._create_user("alice", "password123")
        response = self.client.post(
            "/api/radio/login", json={"username": "alice", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_must_change_password_blocks_companion_login(self):
        self._create_user("alice", "password123", must_change=1)
        response = self.client.post(
            "/api/radio/login", json={"username": "alice", "password": "password123"},
        )
        self.assertEqual(response.status_code, 403)

    def test_successful_login_returns_user_info_and_sets_cookie(self):
        self._create_user("alice", "password123")
        response = self.client.post(
            "/api/radio/login", json={"username": "alice", "password": "password123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["username"], "alice")
        self.assertIn(auth.SESSION_COOKIE, response.headers.get("Set-Cookie", ""))

    def test_unknown_product_header_falls_back_to_companion(self):
        self._create_user("alice", "password123")
        response = self.client.post(
            "/api/radio/login", json={"username": "alice", "password": "password123"},
            headers={"X-Adolar-Product": "something-weird"},
        )
        self.assertEqual(response.status_code, 200)
        with app_module.db.db() as conn:
            product = conn.execute(
                "SELECT product FROM connection_log ORDER BY id DESC LIMIT 1",
            ).fetchone()["product"]
        self.assertEqual(product, "companion")

    def test_blocked_ip_is_rejected_before_checking_credentials(self):
        self._create_user("alice", "password123")
        for _ in range(auth.BF_SOFT_LIMIT):
            self.client.post("/api/radio/login", json={"username": "alice", "password": "wrong"})
        response = self.client.post(
            "/api/radio/login", json={"username": "alice", "password": "password123"},
        )
        self.assertEqual(response.status_code, 429)


class RadioLogoutRouteTests(AuthRouteTestBase):
    def test_clears_session_and_cookie(self):
        self._create_user("alice", "password123")
        self.client.post("/api/radio/login", json={"username": "alice", "password": "password123"})
        response = self.client.post("/api/radio/logout")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


class ChangePasswordRouteTests(AuthRouteTestBase):
    def _login(self, username, password):
        response = self.client.post("/login", data={"username": username, "password": password})
        return response

    def test_get_change_password_redirects_when_not_logged_in(self):
        response = self.client.get("/change-password")
        self.assertEqual(response.status_code, 302)

    def test_get_change_password_ok_when_logged_in(self):
        self._create_user("alice", "password123")
        self._login("alice", "password123")
        self.assertEqual(self.client.get("/change-password").status_code, 200)

    def test_api_change_password_requires_authentication(self):
        response = self.client.post("/api/auth/change-password", json={
            "password": "newpassword1", "password2": "newpassword1",
        })
        self.assertEqual(response.status_code, 401)

    def test_forced_change_does_not_require_old_password(self):
        self._create_user("alice", "password123", must_change=1)
        self._login("alice", "password123")
        response = self.client.post("/api/auth/change-password", json={
            "password": "newpassword1", "password2": "newpassword1",
        })
        self.assertEqual(response.status_code, 200)
        user = auth.get_user_by_name("alice")
        self.assertTrue(auth.verify_password(user, "newpassword1"))

    def test_voluntary_change_requires_correct_old_password(self):
        self._create_user("alice", "password123")
        self._login("alice", "password123")
        response = self.client.post("/api/auth/change-password", json={
            "old_password": "wrong-old-password",
            "password": "newpassword1", "password2": "newpassword1",
        })
        self.assertEqual(response.status_code, 400)

    def test_new_password_must_meet_length_requirement(self):
        self._create_user("alice", "password123", must_change=1)
        self._login("alice", "password123")
        response = self.client.post("/api/auth/change-password", json={
            "password": "short", "password2": "short",
        })
        self.assertEqual(response.status_code, 400)

    def test_new_passwords_must_match(self):
        self._create_user("alice", "password123", must_change=1)
        self._login("alice", "password123")
        response = self.client.post("/api/auth/change-password", json={
            "password": "newpassword1", "password2": "different-password",
        })
        self.assertEqual(response.status_code, 400)


class ApiMeRouteTests(AuthRouteTestBase):
    def test_unauthenticated_returns_401(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_authenticated_user_gets_their_profile(self):
        self._create_user("alice", "password123")
        self.client.post("/login", data={"username": "alice", "password": "password123"})
        response = self.client.get("/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["username"], "alice")

    def test_admin_is_always_reported_as_allowed_everything(self):
        self._create_user("admin", "password123", role="admin")
        self.client.post("/login", data={"username": "admin", "password": "password123"})
        data = self.client.get("/api/me").get_json()
        self.assertTrue(data["allow_download"])
        self.assertTrue(data["allow_playlists"])
        self.assertTrue(data["allow_radio_stations"])


if __name__ == "__main__":
    unittest.main()
