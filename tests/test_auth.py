import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-auth-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-auth-import-control.db"),
)

import auth
import db


class AuthTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "auth.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "auth-control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        auth._bf_state.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        auth._bf_state.clear()
        self.temp.cleanup()


class PasswordHashingTests(AuthTestBase):
    def test_create_user_never_stores_the_plaintext_password(self):
        user_id = auth.create_user("alice", "s3cret-pw")
        with db.db() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        self.assertNotIn("s3cret-pw", row["password_hash"])

    def test_verify_password_accepts_correct_and_rejects_wrong(self):
        auth.create_user("bob", "correct-horse")
        user = auth.get_user_by_name("bob")
        self.assertTrue(auth.verify_password(user, "correct-horse"))
        self.assertFalse(auth.verify_password(user, "wrong-guess"))

    def test_set_password_rotates_hash_and_must_change_flag(self):
        user_id = auth.create_user("carol", "first-pw")
        auth.set_password(user_id, "second-pw", must_change=True)
        user = auth.get_user_by_name("carol")
        self.assertTrue(auth.verify_password(user, "second-pw"))
        self.assertFalse(auth.verify_password(user, "first-pw"))
        self.assertEqual(user["must_change_password"], 1)


class UserManagementTests(AuthTestBase):
    def test_get_user_by_name_is_case_insensitive(self):
        auth.create_user("DavidTest", "pw")
        self.assertIsNotNone(auth.get_user_by_name("davidtest"))
        self.assertIsNotNone(auth.get_user_by_name("DAVIDTEST"))

    def test_user_count_and_get_all_users(self):
        self.assertEqual(auth.user_count(), 0)
        auth.create_user("u1", "pw")
        auth.create_user("u2", "pw", role="admin")
        self.assertEqual(auth.user_count(), 2)
        usernames = {u["username"] for u in auth.get_all_users()}
        self.assertEqual(usernames, {"u1", "u2"})

    def test_get_user_by_id_matches_get_user_by_name(self):
        user_id = auth.create_user("erin", "pw")
        self.assertEqual(auth.get_user_by_id(user_id)["username"], "erin")

    def test_set_user_capability_updates_the_right_column(self):
        user_id = auth.create_user("frank", "pw")
        auth.set_user_capability(user_id, "playlists", False)
        auth.set_user_capability(user_id, "radio_stations", False)
        auth.set_user_capability(user_id, "download", True)
        user = auth.get_user_by_id(user_id)
        self.assertEqual(user["allow_playlists"], 0)
        self.assertEqual(user["allow_radio_stations"], 0)
        self.assertEqual(user["allow_download"], 1)

    def test_set_user_capability_rejects_unknown_capability(self):
        user_id = auth.create_user("gina", "pw")
        with self.assertRaises(ValueError):
            auth.set_user_capability(user_id, "not-a-real-capability", True)

    def test_deactivating_a_user_revokes_all_of_their_sessions(self):
        user_id = auth.create_user("hank", "pw")
        token = auth.create_session(user_id, remember=False)
        self.assertIsNotNone(auth.get_user_by_token(token))
        auth.set_user_active(user_id, False)
        self.assertIsNone(auth.get_user_by_token(token))


class SessionLifecycleTests(AuthTestBase):
    def test_valid_session_resolves_to_its_user(self):
        user_id = auth.create_user("iris", "pw")
        token = auth.create_session(user_id, remember=False)
        resolved = auth.get_user_by_token(token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["id"], user_id)

    def test_expired_session_no_longer_resolves(self):
        user_id = auth.create_user("jack", "pw")
        with mock.patch.object(auth.time, "time", return_value=1_000_000.0):
            token = auth.create_session(user_id, remember=False)
        with mock.patch.object(auth.time, "time", return_value=1_000_000.0 + auth.SESSION_TTL + 1):
            self.assertIsNone(auth.get_user_by_token(token))

    def test_remember_me_session_outlives_the_normal_ttl(self):
        user_id = auth.create_user("kim", "pw")
        with mock.patch.object(auth.time, "time", return_value=1_000_000.0):
            token = auth.create_session(user_id, remember=True)
        with mock.patch.object(auth.time, "time", return_value=1_000_000.0 + auth.SESSION_TTL + 1):
            self.assertIsNotNone(auth.get_user_by_token(token))

    def test_delete_session_invalidates_the_token(self):
        user_id = auth.create_user("liam", "pw")
        token = auth.create_session(user_id, remember=False)
        auth.delete_session(token)
        self.assertIsNone(auth.get_user_by_token(token))

    def test_inactive_user_cannot_authenticate_even_with_a_live_session(self):
        user_id = auth.create_user("mona", "pw")
        token = auth.create_session(user_id, remember=False)
        with db.db() as conn:
            conn.execute("UPDATE users SET is_active=0 WHERE id=?", (user_id,))
        self.assertIsNone(auth.get_user_by_token(token))

    def test_purge_expired_sessions_removes_only_expired_rows(self):
        user_id = auth.create_user("nora", "pw")
        with mock.patch.object(auth.time, "time", return_value=1_000_000.0):
            expired_token = auth.create_session(user_id, remember=False)
        live_token = auth.create_session(user_id, remember=False)

        with mock.patch.object(auth.time, "time", return_value=1_000_000.0 + auth.SESSION_TTL + 1):
            auth.purge_expired_sessions()

        with db.db() as conn:
            remaining = {r["token"] for r in conn.execute("SELECT token FROM sessions")}
        self.assertNotIn(expired_token, remaining)
        self.assertIn(live_token, remaining)


class BruteForceProtectionTests(AuthTestBase):
    def test_no_block_before_any_failures(self):
        blocked, remaining = auth._bf_check("1.2.3.4")
        self.assertFalse(blocked)
        self.assertEqual(remaining, 0)

    def test_soft_block_kicks_in_at_the_soft_limit(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT - 1):
                auth._bf_record_failure("5.5.5.5")
            blocked, _ = auth._bf_check("5.5.5.5")
            self.assertFalse(blocked, "should not block below the soft limit")

            auth._bf_record_failure("5.5.5.5")  # reaches BF_SOFT_LIMIT
            blocked, remaining = auth._bf_check("5.5.5.5")
        self.assertTrue(blocked)
        self.assertEqual(remaining, auth.BF_SOFT_BLOCK)

    def test_soft_block_expires_after_its_window(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("6.6.6.6")
        with mock.patch.object(auth.time, "time", return_value=1000.0 + auth.BF_SOFT_BLOCK + 1):
            blocked, _ = auth._bf_check("6.6.6.6")
        self.assertFalse(blocked)

    def test_hard_limit_blocks_effectively_permanently(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_HARD_LIMIT):
                auth._bf_record_failure("7.7.7.7")
            blocked, remaining = auth._bf_check("7.7.7.7")
        self.assertTrue(blocked)
        self.assertEqual(remaining, auth.BF_HARD_BLOCK)

    def test_old_failures_outside_the_window_do_not_count(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT - 1):
                auth._bf_record_failure("8.8.8.8")
        # Jump past the rolling window: old attempts should be purged, so one
        # more failure alone should not trip the soft limit.
        with mock.patch.object(auth.time, "time", return_value=1000.0 + auth.BF_WINDOW + 1):
            auth._bf_record_failure("8.8.8.8")
            blocked, _ = auth._bf_check("8.8.8.8")
        self.assertFalse(blocked)

    def test_a_block_is_persisted_to_the_database(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("9.9.9.9")
        with db.db() as conn:
            row = conn.execute(
                "SELECT blocked_until FROM login_blocks WHERE ip=?", ("9.9.9.9",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["blocked_until"], 1000.0 + auth.BF_SOFT_BLOCK)

    def test_unblock_ip_clears_memory_and_persisted_state(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("10.10.10.10")
        auth.unblock_ip("10.10.10.10")
        blocked, _ = auth._bf_check("10.10.10.10")
        self.assertFalse(blocked)
        with db.db() as conn:
            row = conn.execute(
                "SELECT 1 FROM login_blocks WHERE ip=?", ("10.10.10.10",),
            ).fetchone()
        self.assertIsNone(row)

    def test_load_persisted_blocks_restores_active_blocks_after_a_restart(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("11.11.11.11")
        # Simulate a process restart: in-memory tracker is empty, but the DB
        # still has the block row.
        auth._bf_state.clear()
        blocked_before_reload, _ = auth._bf_check("11.11.11.11")
        self.assertFalse(blocked_before_reload)

        with mock.patch.object(auth.time, "time", return_value=1000.0 + 5):
            auth.load_persisted_blocks()
            blocked_after_reload, remaining = auth._bf_check("11.11.11.11")
        self.assertTrue(blocked_after_reload)
        self.assertGreater(remaining, 0)

    def test_load_persisted_blocks_ignores_already_expired_rows(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("12.12.12.12")
        auth._bf_state.clear()
        with mock.patch.object(auth.time, "time", return_value=1000.0 + auth.BF_SOFT_BLOCK + 1):
            auth.load_persisted_blocks()
            blocked, _ = auth._bf_check("12.12.12.12")
        self.assertFalse(blocked)

    def test_get_blocked_ips_lists_only_currently_active_blocks(self):
        with mock.patch.object(auth.time, "time", return_value=1000.0):
            for _ in range(auth.BF_SOFT_LIMIT):
                auth._bf_record_failure("13.13.13.13")
        with mock.patch.object(auth.time, "time", return_value=1000.0 + 5):
            blocked_ips = {row["ip"] for row in auth.get_blocked_ips()}
        self.assertIn("13.13.13.13", blocked_ips)


class CapabilityMatrixTests(AuthTestBase):
    def _user(self, **overrides):
        base = {
            "id": 1, "username": "u", "role": "user",
            "allow_download": 0, "allow_playlists": 1, "allow_radio_stations": 1,
        }
        base.update(overrides)
        return base

    def test_admin_can_do_everything_regardless_of_flags_or_settings(self):
        admin = self._user(role="admin", allow_download=0, allow_playlists=0, allow_radio_stations=0)
        with mock.patch.object(db, "get_setting", return_value="0"):
            for capability in (
                "view_web", "create_playlists", "create_radio_stations", "download_tracks",
            ):
                self.assertTrue(auth.can(admin, capability))

    def test_view_web_for_anonymous_follows_the_global_setting(self):
        with mock.patch.object(db, "get_setting", return_value="0"):
            self.assertFalse(auth.can(None, "view_web"))
        with mock.patch.object(db, "get_setting", return_value="1"):
            self.assertTrue(auth.can(None, "view_web"))

    def test_view_web_is_always_true_for_a_logged_in_user(self):
        with mock.patch.object(db, "get_setting", return_value="0"):
            self.assertTrue(auth.can(self._user(), "view_web"))

    def test_create_playlists_requires_both_global_setting_and_user_flag(self):
        user = self._user(allow_playlists=1)
        with mock.patch.object(db, "get_setting", return_value="1"):
            self.assertTrue(auth.can(user, "create_playlists"))
        with mock.patch.object(db, "get_setting", return_value="0"):
            self.assertFalse(auth.can(user, "create_playlists"))
        with mock.patch.object(db, "get_setting", return_value="1"):
            self.assertFalse(auth.can(self._user(allow_playlists=0), "create_playlists"))

    def test_create_radio_stations_requires_both_global_setting_and_user_flag(self):
        user = self._user(allow_radio_stations=1)
        with mock.patch.object(db, "get_setting", return_value="1"):
            self.assertTrue(auth.can(user, "create_radio_stations"))
        with mock.patch.object(db, "get_setting", return_value="0"):
            self.assertFalse(auth.can(user, "create_radio_stations"))

    def test_download_tracks_only_depends_on_the_user_flag(self):
        with mock.patch.object(db, "get_setting", return_value="0"):
            self.assertTrue(auth.can(self._user(allow_download=1), "download_tracks"))
            self.assertFalse(auth.can(self._user(allow_download=0), "download_tracks"))

    def test_unknown_capability_is_denied_by_default(self):
        self.assertFalse(auth.can(self._user(), "time-travel"))

    def test_anonymous_user_has_no_capability_other_than_view_web(self):
        with mock.patch.object(db, "get_setting", return_value="1"):
            self.assertFalse(auth.can(None, "create_playlists"))
            self.assertFalse(auth.can(None, "download_tracks"))


if __name__ == "__main__":
    unittest.main()
