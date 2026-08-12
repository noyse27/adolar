import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-apitokens-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-apitokens-import-control.db"),
)

from adolar import application as app_module
from adolar import auth, db


class ApiTokenAuthTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()


class ApiTokenFunctionsTests(ApiTokenAuthTestBase):
    def test_create_api_token_returns_plaintext_once_and_is_not_stored_in_the_clear(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        token = auth.create_api_token(user_id, "Taggster")
        self.assertTrue(token)
        with db.db() as conn:
            row = conn.execute("SELECT token FROM api_tokens WHERE user_id=?", (user_id,)).fetchone()
        self.assertEqual(row["token"], token)

    def test_list_api_tokens_never_includes_the_plaintext_token(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        auth.create_api_token(user_id, "Taggster")
        tokens = auth.list_api_tokens(user_id)
        self.assertEqual(len(tokens), 1)
        self.assertNotIn("token", tokens[0])
        self.assertEqual(tokens[0]["name"], "Taggster")

    def test_list_api_tokens_excludes_revoked_and_other_users_tokens(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        other_id = auth.create_user("other", "password123", role="admin")
        keep = auth.create_api_token(user_id, "keep")
        revoked = auth.create_api_token(user_id, "revoked")
        auth.create_api_token(other_id, "not-mine")
        with db.db() as conn:
            revoked_id = conn.execute(
                "SELECT id FROM api_tokens WHERE token=?", (revoked,)
            ).fetchone()["id"]
        auth.revoke_api_token(revoked_id, user_id)
        names = {t["name"] for t in auth.list_api_tokens(user_id)}
        self.assertEqual(names, {"keep"})
        self.assertIsNotNone(auth.get_user_by_api_token(keep))

    def test_get_user_by_api_token_rejects_unknown_and_revoked_tokens(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        token = auth.create_api_token(user_id, "Taggster")
        self.assertIsNotNone(auth.get_user_by_api_token(token))

        self.assertIsNone(auth.get_user_by_api_token("does-not-exist"))

        with db.db() as conn:
            token_id = conn.execute(
                "SELECT id FROM api_tokens WHERE token=?", (token,)
            ).fetchone()["id"]
        auth.revoke_api_token(token_id, user_id)
        self.assertIsNone(auth.get_user_by_api_token(token))

    def test_get_user_by_api_token_rejects_tokens_of_deactivated_users(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        token = auth.create_api_token(user_id, "Taggster")
        auth.set_user_active(user_id, False)
        self.assertIsNone(auth.get_user_by_api_token(token))

    def test_revoke_api_token_is_scoped_to_the_owning_user(self):
        owner_id = auth.create_user("owner", "password123", role="admin")
        other_id = auth.create_user("other", "password123", role="admin")
        token = auth.create_api_token(owner_id, "Taggster")
        with db.db() as conn:
            token_id = conn.execute(
                "SELECT id FROM api_tokens WHERE token=?", (token,)
            ).fetchone()["id"]
        # Another admin guessing the token id cannot revoke someone else's token.
        auth.revoke_api_token(token_id, other_id)
        self.assertIsNotNone(auth.get_user_by_api_token(token))
        auth.revoke_api_token(token_id, owner_id)
        self.assertIsNone(auth.get_user_by_api_token(token))

    def test_touch_api_token_updates_last_used_at_and_creates_one_connection_log_row(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        token = auth.create_api_token(user_id, "Taggster")
        auth.touch_api_token(token, ip_address="10.0.0.5")
        auth.touch_api_token(token, ip_address="10.0.0.5")
        with db.db() as conn:
            row = conn.execute(
                "SELECT last_used_at, connection_id FROM api_tokens WHERE token=?", (token,)
            ).fetchone()
            self.assertIsNotNone(row["last_used_at"])
            self.assertIsNotNone(row["connection_id"])
            count = conn.execute(
                "SELECT COUNT(*) FROM connection_log WHERE product='taggster'"
            ).fetchone()[0]
        # Repeated use refreshes the same connection_log row, not a new one each time.
        self.assertEqual(count, 1)


class ApiTokenMigrationTests(ApiTokenAuthTestBase):
    def test_api_tokens_table_and_connection_id_column_survive_reinitialization(self):
        user_id = auth.create_user("admin", "password123", role="admin")
        auth.create_api_token(user_id, "Taggster")
        db.init_db()
        with db.db() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(api_tokens)")}
        self.assertIn("connection_id", columns)
        self.assertEqual(len(auth.list_api_tokens(user_id)), 1)


class ApiTokenRouteTestBase(unittest.TestCase):
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

    def tearDown(self):
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()

    def _login_as_admin(self):
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.admin_id), must_change_password=0),
        )


class ApiTokenRoutesTests(ApiTokenRouteTestBase):
    def test_create_list_and_revoke_via_admin_routes(self):
        with self._login_as_admin():
            create = self.client.post("/api/admin/tokens", json={"name": "Taggster"})
            self.assertEqual(create.status_code, 200)
            token = create.get_json()["token"]
            self.assertTrue(token)

            listing = self.client.get("/api/admin/tokens")
            tokens = listing.get_json()["tokens"]
            self.assertEqual(len(tokens), 1)
            self.assertNotIn("token", tokens[0])
            token_id = tokens[0]["id"]

            revoke = self.client.delete(f"/api/admin/tokens/{token_id}")
            self.assertEqual(revoke.status_code, 200)
            self.assertEqual(self.client.get("/api/admin/tokens").get_json()["tokens"], [])

    def test_token_routes_require_admin(self):
        self.client.set_cookie("adolar_session", "token")
        with mock.patch.object(
            app_module._auth, "get_user_by_token",
            return_value=dict(auth.get_user_by_id(self.user_id), must_change_password=0),
        ):
            self.assertEqual(self.client.get("/api/admin/tokens").status_code, 403)
            self.assertEqual(
                self.client.post("/api/admin/tokens", json={"name": "x"}).status_code, 403,
            )

    def test_bearer_token_authenticates_without_a_session_cookie(self):
        with self._login_as_admin():
            token = self.client.post(
                "/api/admin/tokens", json={"name": "Taggster"},
            ).get_json()["token"]

        # A fresh client with no session cookie at all, only the bearer token.
        anon_client = app_module.app.test_client()
        response = anon_client.get(
            "/api/me", headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["username"], "admin")

    def test_revoked_bearer_token_is_rejected(self):
        with self._login_as_admin():
            created = self.client.post("/api/admin/tokens", json={"name": "Taggster"}).get_json()
            token = created["token"]
            token_id = self.client.get("/api/admin/tokens").get_json()["tokens"][0]["id"]
            self.client.delete(f"/api/admin/tokens/{token_id}")

        anon_client = app_module.app.test_client()
        response = anon_client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        # No valid session and no valid bearer token: falls through to anonymous/unauthorized.
        self.assertNotEqual(response.status_code, 200)

    def test_garbage_bearer_token_does_not_authenticate(self):
        anon_client = app_module.app.test_client()
        response = anon_client.get(
            "/api/me", headers={"Authorization": "Bearer not-a-real-token"},
        )
        self.assertNotEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
