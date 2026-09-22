import os
import shutil
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar-demo-mode-import.db"))

from adolar import application as app_module
from adolar import auth as _auth
from adolar import demo_mode


class DemoModeConfigTests(unittest.TestCase):
    """_parse_reset_minutes() reads os.environ on every call (unlike the
    module-level DEMO_RESET_MINUTES, computed once at import) - it can be
    exercised directly without reimporting the module."""

    def test_defaults_to_60_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADOLAR_DEMO_RESET_MINUTES", None)
            self.assertEqual(demo_mode._parse_reset_minutes(), 60)

    def test_defaults_to_60_when_not_a_number(self):
        with mock.patch.dict(os.environ, {"ADOLAR_DEMO_RESET_MINUTES": "not-a-number"}):
            self.assertEqual(demo_mode._parse_reset_minutes(), 60)

    def test_clamps_below_minimum(self):
        with mock.patch.dict(os.environ, {"ADOLAR_DEMO_RESET_MINUTES": "1"}):
            self.assertEqual(demo_mode._parse_reset_minutes(), 5)

    def test_clamps_above_maximum(self):
        with mock.patch.dict(os.environ, {"ADOLAR_DEMO_RESET_MINUTES": "999999"}):
            self.assertEqual(demo_mode._parse_reset_minutes(), 1440)


class DemoModeResetTests(unittest.TestCase):
    ADMIN_ID = 91

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music_root = os.path.join(self.temp.name, "music")
        os.makedirs(self.music_root)
        self.db_path = os.path.join(self.temp.name, "adolar.db")
        self.control_db_path = os.path.join(self.temp.name, "control.db")

        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db, "CONTROL_DB_PATH", self.control_db_path),
            mock.patch.object(app_module, "MUSIC_ROOT", self.music_root),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_assert_seeds_a_fresh_empty_database(self):
        self.assertEqual(_auth.user_count(), 0)
        demo_mode.assert_demo_safe_to_manage()

        admin = _auth.get_user_by_name(demo_mode.DEMO_ADMIN_USERNAME)
        self.assertIsNotNone(admin)
        self.assertEqual(admin["role"], "admin")
        self.assertEqual(admin["must_change_password"], 0)
        listener = _auth.get_user_by_name(demo_mode.DEMO_USER_USERNAME)
        self.assertIsNotNone(listener)
        self.assertEqual(listener["role"], "user")

        self.assertEqual(app_module.db.get_setting("demo_managed"), "1")

    def test_assert_is_idempotent_once_marked(self):
        demo_mode.assert_demo_safe_to_manage()
        before = _auth.user_count()

        demo_mode.assert_demo_safe_to_manage()

        self.assertEqual(_auth.user_count(), before)

    def test_assert_refuses_a_database_with_real_users_and_no_marker(self):
        _auth.create_user("real-user", "x", role="user")

        with self.assertRaisesRegex(RuntimeError, "refusing to start"):
            demo_mode.assert_demo_safe_to_manage()

    def test_reset_wipes_tracks_and_users_but_keeps_them_reseeded(self):
        demo_mode.reset_demo_data()
        with app_module.db.db() as conn:
            conn.execute(
                "INSERT INTO tracks (path, title) VALUES (?, 'Manual Track')",
                (os.path.join(self.music_root, "manual.mp3"),),
            )
            track_count_before = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        self.assertEqual(track_count_before, 1)

        demo_mode.reset_demo_data()

        with app_module.db.db() as conn:
            # The manually-inserted track (not a real file scanner.py would
            # find) is gone; reset_demo_data only reseeds from music_root.
            remaining = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE title='Manual Track'"
            ).fetchone()[0]
        self.assertEqual(remaining, 0)
        self.assertIsNotNone(_auth.get_user_by_name(demo_mode.DEMO_ADMIN_USERNAME))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
    def test_reset_scans_real_demo_tracks_from_music_root(self):
        import subprocess

        track_path = os.path.join(self.music_root, "track.mp3")
        subprocess.run(  # noqa: S603 - fixed args + a path this test created, no untrusted input
            [
                shutil.which("ffmpeg"), "-y", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-metadata", "title=Testlied",
                "-metadata", "artist=Testband",
                "-id3v2_version", "3",
                track_path,
            ],
            check=True, stdin=subprocess.DEVNULL,
        )

        demo_mode.reset_demo_data()

        with app_module.db.db() as conn:
            track = conn.execute("SELECT title, artist FROM tracks").fetchone()
        self.assertEqual(track["title"], "Testlied")
        self.assertEqual(track["artist"], "Testband")

    def test_demo_status_reflects_last_reset(self):
        demo_mode._last_reset_at = None
        demo_mode.reset_demo_data()

        with mock.patch.object(demo_mode, "DEMO_MODE", True):
            status = demo_mode.demo_status()

        self.assertTrue(status["active"])
        self.assertIsNotNone(status["last_reset_at"])
        self.assertEqual(status["admin_username"], demo_mode.DEMO_ADMIN_USERNAME)

    def test_demo_status_inactive_when_demo_mode_off(self):
        with mock.patch.object(demo_mode, "DEMO_MODE", False):
            self.assertEqual(demo_mode.demo_status(), {"active": False})


class BlockWhenDemoTests(unittest.TestCase):
    def test_blocks_and_returns_403_when_demo_mode_active(self):
        calls = []

        @demo_mode.block_when_demo("Testaktion")
        def handler():
            calls.append("called")
            return "ok"

        with app_module.app.test_request_context(), mock.patch.object(demo_mode, "DEMO_MODE", True):
            response, status = handler()
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])
        self.assertIn("Testaktion", response.get_json()["error"])

    def test_passes_through_when_demo_mode_inactive(self):
        @demo_mode.block_when_demo("Testaktion")
        def handler():
            return "ok"

        with mock.patch.object(demo_mode, "DEMO_MODE", False):
            self.assertEqual(handler(), "ok")


class DemoStatusRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_returns_inactive_when_demo_mode_off(self):
        with mock.patch.object(demo_mode, "DEMO_MODE", False):
            response = self.client.get("/api/demo/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"active": False})

    def test_is_reachable_without_authentication(self):
        # PUBLIC_PREFIXES must list this route, or auth.before_request would
        # redirect/401 it before this view ever runs.
        with mock.patch.object(demo_mode, "DEMO_MODE", False):
            response = self.client.get("/api/demo/status")
        self.assertNotEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
