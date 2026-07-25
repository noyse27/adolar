import os
import tempfile
import unittest
from unittest import mock

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar-backup-config-test.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_temp_dir.name, "adolar-backup-config-test-control.db"),
)

import app as app_module


class BackupRootSettingTests(unittest.TestCase):
    def test_falls_back_to_env_seeded_default_when_unset(self):
        with mock.patch.object(app_module.db, "get_setting", return_value=None):
            self.assertEqual(app_module._backup_root(), app_module._BACKUP_DEFAULT_ROOT)

    def test_uses_admin_configured_path_once_set(self):
        with mock.patch.object(app_module.db, "get_setting", return_value="/mnt/custom-backups"):
            self.assertEqual(app_module._backup_root(), "/mnt/custom-backups")


class BackupConfigEndpointTests(unittest.TestCase):
    ADMIN_ID = 91

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
        with app_module.db.db() as conn:
            conn.execute(
                """INSERT INTO users (id, username, password_hash, role, must_change_password)
                   VALUES (?, 'admin', 'unused', 'admin', 0)""",
                (self.ADMIN_ID,),
            )
        self.admin = {
            "id": self.ADMIN_ID,
            "username": "admin",
            "role": "admin",
            "allow_download": 1,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "backup-config-token")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _as_admin(self):
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=self.admin)

    def test_valid_path_is_persisted_and_becomes_the_configured_root(self):
        new_root = os.path.join(self.temp.name, "backups")
        with self._as_admin():
            response = self.client.put("/api/admin/backups/config", json={
                "enabled": True, "hour": 4, "retention": 5, "path": new_root,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["configured_path"], new_root)
        self.assertEqual(app_module._backup_root(), new_root)
        self.assertTrue(os.path.isdir(new_root))

    def test_unwritable_path_is_rejected_and_not_persisted(self):
        previous = app_module._backup_root()
        unwritable = os.path.join(self.temp.name, "no-such-drive-letter-x", "backups")
        with self._as_admin(), mock.patch.object(
            app_module.backup_service, "ensure_backup_root", side_effect=OSError("nope"),
        ):
            response = self.client.put("/api/admin/backups/config", json={
                "enabled": True, "hour": 4, "retention": 5, "path": unwritable,
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(app_module._backup_root(), previous)

    def test_omitting_path_leaves_existing_configuration_untouched(self):
        with self._as_admin():
            self.client.put("/api/admin/backups/config", json={
                "enabled": True, "hour": 4, "retention": 5,
                "path": os.path.join(self.temp.name, "backups"),
            })
            response = self.client.put("/api/admin/backups/config", json={
                "enabled": False, "hour": 5, "retention": 6,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            app_module._backup_root(), os.path.join(self.temp.name, "backups"),
        )


if __name__ == "__main__":
    unittest.main()
