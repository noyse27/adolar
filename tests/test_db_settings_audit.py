import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-settings-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-settings-import-control.db"),
)

from adolar import db


class DbTestBase(unittest.TestCase):
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
        self.temp.cleanup()


class SettingsTests(DbTestBase):
    def test_get_setting_returns_default_when_absent(self):
        self.assertEqual(db.get_setting("nope", "fallback"), "fallback")
        self.assertIsNone(db.get_setting("nope"))

    def test_set_setting_then_get_setting_round_trips(self):
        db.set_setting("backup_hour", "4")
        self.assertEqual(db.get_setting("backup_hour"), "4")

    def test_set_setting_overwrites_previous_value(self):
        db.set_setting("key", "one")
        db.set_setting("key", "two")
        self.assertEqual(db.get_setting("key"), "two")

    def test_del_setting_removes_it(self):
        db.set_setting("key", "value")
        db.del_setting("key")
        self.assertIsNone(db.get_setting("key"))

    def test_del_setting_on_missing_key_does_not_raise(self):
        db.del_setting("never-existed")  # should be a silent no-op


class ClaimOnceTests(DbTestBase):
    def test_first_claim_succeeds_second_does_not(self):
        self.assertTrue(db.claim_once("job:2026-07-25"))
        self.assertFalse(db.claim_once("job:2026-07-25"))

    def test_different_keys_can_each_be_claimed_once(self):
        self.assertTrue(db.claim_once("job-a"))
        self.assertTrue(db.claim_once("job-b"))


class AuditLogTests(DbTestBase):
    def setUp(self):
        super().setUp()
        with db.db() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (1, 'admin', 'x')",
            )

    def test_log_audit_then_get_audit_log_returns_it_with_resolved_actor_name(self):
        db.log_audit(1, "backup.created", "abc123", '{"size": 42}')
        entries = db.get_audit_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "backup.created")
        self.assertEqual(entries[0]["target"], "abc123")
        self.assertEqual(entries[0]["actor"], "admin")

    def test_audit_log_with_no_actor_shows_system(self):
        db.log_audit(None, "backup.created", "auto", "{}")
        entries = db.get_audit_log()
        self.assertEqual(entries[0]["actor"], "System")

    def test_get_audit_log_orders_newest_first(self):
        db.log_audit(1, "first", "", "")
        db.log_audit(1, "second", "", "")
        entries = db.get_audit_log()
        self.assertEqual([e["action"] for e in entries], ["second", "first"])

    def test_get_audit_log_respects_limit(self):
        for i in range(5):
            db.log_audit(1, f"action-{i}", "", "")
        self.assertEqual(len(db.get_audit_log(limit=2)), 2)

    def test_get_audit_log_limit_is_clamped_to_a_sane_range(self):
        db.log_audit(1, "one-entry", "", "")
        # limit=0 and negative limits should not blow up or return nothing.
        self.assertEqual(len(db.get_audit_log(limit=0)), 1)


class MigrateTrackPathsTests(DbTestBase):
    def setUp(self):
        super().setUp()
        with db.db() as conn:
            conn.execute("INSERT INTO tracks (path, title) VALUES ('/music/old/a.mp3', 'A')")
            conn.execute("INSERT INTO tracks (path, title) VALUES ('/music/old/sub/b.mp3', 'B')")
            conn.execute("INSERT INTO tracks (path, title) VALUES ('/music/other/c.mp3', 'C')")

    def test_rewrites_paths_under_the_old_root_only(self):
        updated = db.migrate_track_paths("/music/old", "/music/new")
        self.assertEqual(updated, 2)
        with db.db() as conn:
            paths = {row["title"]: row["path"] for row in conn.execute("SELECT title, path FROM tracks")}
        self.assertEqual(paths["A"], "/music/new/a.mp3")
        self.assertEqual(paths["B"], "/music/new/sub/b.mp3")
        self.assertEqual(paths["C"], "/music/other/c.mp3")

    def test_trailing_slash_on_old_root_is_tolerated(self):
        updated = db.migrate_track_paths("/music/old/", "/music/new")
        self.assertEqual(updated, 2)


if __name__ == "__main__":
    unittest.main()
