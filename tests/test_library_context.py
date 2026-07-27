import os
import tempfile
import threading
import unittest
from unittest import mock

import db
import library_context


class LibraryContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.control_path = os.path.join(self.temp.name, "control.db")
        self.default_path = os.path.join(self.temp.name, "default.db")
        self.first_path = os.path.join(self.temp.name, "first.db")
        self.second_path = os.path.join(self.temp.name, "second.db")
        self.patches = [
            mock.patch.object(db, "DB_PATH", self.default_path),
            mock.patch.object(db, "CONTROL_DB_PATH", self.control_path),
        ]
        for patch in self.patches:
            patch.start()
        for path, root in (
            (self.first_path, "/music/first"),
            (self.second_path, "/music/second"),
        ):
            with library_context.bind(path, root):
                db.init_db()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_nested_bind_restores_the_outer_snapshot(self):
        with library_context.bind(self.first_path, "/music/first"):
            self.assertEqual(db.current_db_path(), self.first_path)
            self.assertEqual(library_context.music_root("fallback"), "/music/first")
            with library_context.bind(self.second_path, "/music/second"):
                self.assertEqual(db.current_db_path(), self.second_path)
                self.assertEqual(library_context.music_root("fallback"), "/music/second")
            self.assertEqual(db.current_db_path(), self.first_path)
        self.assertEqual(db.current_db_path(), self.default_path)

    def test_parallel_threads_keep_writes_in_their_own_content_database(self):
        ready = threading.Barrier(3)
        release = threading.Event()
        errors = []

        def write(path, root, title):
            try:
                with library_context.bind(path, root):
                    ready.wait(timeout=2)
                    release.wait(timeout=2)
                    with db.db() as conn:
                        conn.execute(
                            "INSERT INTO tracks (path, title) VALUES (?, ?)",
                            (f"/{title}.mp3", title),
                        )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(
            target=write, args=(self.first_path, "/music/first", "First"),
        )
        second = threading.Thread(
            target=write, args=(self.second_path, "/music/second", "Second"),
        )
        first.start()
        second.start()
        ready.wait(timeout=2)
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        for path, root, expected in (
            (self.first_path, "/music/first", ["First"]),
            (self.second_path, "/music/second", ["Second"]),
        ):
            with library_context.bind(path, root), db.db() as conn:
                titles = [
                    row["title"]
                    for row in conn.execute("SELECT title FROM tracks").fetchall()
                ]
            self.assertEqual(titles, expected)

    def test_wrapped_background_callable_keeps_captured_snapshot(self):
        with library_context.bind(self.first_path, "/music/first"):
            worker = library_context.wrapped(
                lambda: (
                    db.current_db_path(),
                    library_context.music_root("fallback"),
                ),
                db.current_db_path(),
                library_context.music_root("fallback"),
            )
        with library_context.bind(self.second_path, "/music/second"):
            self.assertEqual(worker(), (self.first_path, "/music/first"))


if __name__ == "__main__":
    unittest.main()
