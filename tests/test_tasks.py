import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-tasks-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-tasks-import-control.db"),
)

import db  # noqa: E402
import tasks  # noqa: E402


class TasksTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        tasks._running.clear()

    def tearDown(self):
        tasks._running.clear()
        for p in self.patches:
            p.stop()
        self.temp.cleanup()


class RunningTaskLifecycleTests(TasksTestBase):
    def test_start_registers_a_running_task_with_the_given_type_and_trigger(self):
        task_id = tasks.start("scan", trigger="manual")
        [task] = tasks.running()
        self.assertEqual(task["task_type"], "scan")
        self.assertEqual(task["trigger"], "manual")
        self.assertIsNone(task["current"])
        self.assertIn("started_at", task)
        tasks.finish(task_id)

    def test_update_sets_progress_fields_on_the_running_task(self):
        task_id = tasks.start("scan")
        tasks.update(task_id, current=3, total=10, detail="3 von 10 Dateien")
        [task] = tasks.running()
        self.assertEqual(task["current"], 3)
        self.assertEqual(task["total"], 10)
        self.assertEqual(task["detail"], "3 von 10 Dateien")
        tasks.finish(task_id)

    def test_update_on_unknown_task_id_is_a_silent_no_op(self):
        tasks.update(999999, current=1)  # must not raise

    def test_finish_on_unknown_task_id_is_a_silent_no_op(self):
        tasks.finish(999999)  # must not raise
        self.assertEqual(tasks.recent(), [])

    def test_finish_removes_task_from_running_list(self):
        task_id = tasks.start("thumbnails")
        tasks.finish(task_id)
        self.assertEqual(tasks.running(), [])

    def test_two_concurrently_started_tasks_get_distinct_ids_and_both_show_as_running(self):
        first = tasks.start("scan")
        second = tasks.start("bpm_analyze")
        self.assertNotEqual(first, second)
        types = {t["task_type"] for t in tasks.running()}
        self.assertEqual(types, {"scan", "bpm_analyze"})
        tasks.finish(first)
        tasks.finish(second)


class TaskHistoryTests(TasksTestBase):
    def test_finish_persists_a_history_entry_with_status_and_detail(self):
        task_id = tasks.start("db_optimize", trigger="manual")
        tasks.finish(task_id, status="completed", detail="ok")
        [entry] = tasks.recent()
        self.assertEqual(entry["task_type"], "db_optimize")
        self.assertEqual(entry["trigger"], "manual")
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["detail"], "ok")
        self.assertGreaterEqual(entry["finished_at"], entry["started_at"])

    def test_failed_status_is_preserved(self):
        task_id = tasks.start("bpm_tags")
        tasks.finish(task_id, status="failed", detail="librosa missing")
        [entry] = tasks.recent()
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["detail"], "librosa missing")

    def test_recent_is_ordered_newest_first(self):
        for name in ("scan", "bpm_analyze", "thumbnails"):
            tasks.finish(tasks.start(name))
        names = [t["task_type"] for t in tasks.recent()]
        self.assertEqual(names, ["thumbnails", "bpm_analyze", "scan"])

    def test_recent_respects_the_limit_argument(self):
        for _ in range(5):
            tasks.finish(tasks.start("scan"))
        self.assertEqual(len(tasks.recent(limit=2)), 2)

    def test_history_is_capped_at_history_limit_rows(self):
        with mock.patch.object(tasks, "HISTORY_LIMIT", 3):
            for _ in range(5):
                tasks.finish(tasks.start("scan"))
            with db.db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM control.task_history").fetchone()[0]
        self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
