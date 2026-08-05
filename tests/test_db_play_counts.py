import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-playcounts-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-playcounts-import-control.db"),
)

import db


class PlayCountTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        with db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path, title) VALUES ('/music/a.mp3', 'A')")
            self.track_id = cur.lastrowid

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _track_row(self):
        with db.db() as conn:
            return dict(conn.execute(
                "SELECT * FROM tracks WHERE id=?", (self.track_id,),
            ).fetchone())


class IncrementPlayCountTests(PlayCountTestBase):
    def test_increments_and_returns_new_count_and_path(self):
        count, path = db.increment_play_count(self.track_id)
        self.assertEqual(count, 1)
        self.assertEqual(path, "/music/a.mp3")
        count2, _ = db.increment_play_count(self.track_id)
        self.assertEqual(count2, 2)

    def test_missing_track_returns_zero_and_none(self):
        self.assertEqual(db.increment_play_count(999999), (0, None))


class RecordUserPlayTests(PlayCountTestBase):
    def test_contributing_play_increments_archive_count_and_marks_tag_dirty(self):
        new_count, path = db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)
        self.assertEqual(new_count, 1)
        self.assertEqual(path, "/music/a.mp3")
        row = self._track_row()
        self.assertEqual(row["play_count"], 1)
        self.assertEqual(row["play_count_tag_dirty"], 1)

    def test_non_contributing_play_does_not_touch_archive_count_or_dirty_flag(self):
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=False)
        row = self._track_row()
        self.assertEqual(row["play_count"], 0)
        self.assertEqual(row["play_count_tag_dirty"], 0)

    def test_records_a_per_user_play_count_row(self):
        db.record_user_play(user_id=7, track_id=self.track_id, contributes=False)
        db.record_user_play(user_id=7, track_id=self.track_id, contributes=False)
        with db.db() as conn:
            row = conn.execute(
                "SELECT count FROM user_play_counts WHERE user_id=? AND track_id=?",
                (7, self.track_id),
            ).fetchone()
        self.assertEqual(row["count"], 2)

    def test_exposure_only_play_skips_personal_count_but_keeps_archive_count(self):
        new_count, _ = db.record_user_play(
            user_id=7, track_id=self.track_id, contributes=True,
            record_personal=False,
        )
        self.assertEqual(new_count, 1)
        with db.db() as conn:
            personal = conn.execute(
                "SELECT 1 FROM user_play_counts WHERE user_id=? AND track_id=?",
                (7, self.track_id),
            ).fetchone()
        self.assertIsNone(personal)

    def test_different_users_get_independent_play_counts(self):
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=False)
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=False)
        db.record_user_play(user_id=2, track_id=self.track_id, contributes=False)
        with db.db() as conn:
            counts = {
                row["user_id"]: row["count"]
                for row in conn.execute(
                    "SELECT user_id, count FROM user_play_counts WHERE track_id=?", (self.track_id,),
                )
            }
        self.assertEqual(counts, {1: 2, 2: 1})

    def test_missing_track_returns_none_none(self):
        self.assertEqual(
            db.record_user_play(user_id=1, track_id=999999, contributes=True), (None, None),
        )


class SetAndMergeArchiveCountTests(PlayCountTestBase):
    def test_set_play_count_overwrites_directly(self):
        db.set_play_count(self.track_id, 42)
        self.assertEqual(self._track_row()["play_count"], 42)

    def test_merge_archive_play_count_raises_but_never_lowers(self):
        db.set_play_count(self.track_id, 10)
        self.assertTrue(db.merge_archive_play_count(self.track_id, 20))
        self.assertEqual(self._track_row()["play_count"], 20)

        self.assertFalse(db.merge_archive_play_count(self.track_id, 5))
        self.assertEqual(self._track_row()["play_count"], 20)

    def test_merge_archive_play_count_marks_tag_dirty_on_raise(self):
        self.assertTrue(db.merge_archive_play_count(self.track_id, 5))
        self.assertEqual(self._track_row()["play_count_tag_dirty"], 1)


class DirtyTagWorkflowTests(PlayCountTestBase):
    def test_dirty_track_appears_in_get_dirty_play_count_tags(self):
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)
        dirty = db.get_dirty_play_count_tags()
        self.assertEqual([d["id"] for d in dirty], [self.track_id])

    def test_marking_written_clears_the_dirty_flag(self):
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)
        db.mark_play_count_tag_written(self.track_id, written_count=1)
        self.assertEqual(db.get_dirty_play_count_tags(), [])

    def test_marking_written_is_ignored_if_the_count_moved_on_in_the_meantime(self):
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)  # play_count now 2
        # A stale write for the old count=1 should not clear the flag for count=2.
        db.mark_play_count_tag_written(self.track_id, written_count=1)
        self.assertEqual(len(db.get_dirty_play_count_tags()), 1)

    def test_get_play_count_tag_status_reports_pending_count(self):
        self.assertEqual(db.get_play_count_tag_status()["pending"], 0)
        db.record_user_play(user_id=1, track_id=self.track_id, contributes=True)
        self.assertEqual(db.get_play_count_tag_status()["pending"], 1)


if __name__ == "__main__":
    unittest.main()
