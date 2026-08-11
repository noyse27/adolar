import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-deluser-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-deluser-import-control.db"),
)

from adolar import auth, db


class DeleteUserCleansUpOrphanedReferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "deluser.db"))
        self.control_db_patch = mock.patch.object(
            db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "deluser-control.db"),
        )
        self.db_patch.start()
        self.control_db_patch.start()
        db.init_db()
        with db.db() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (1, 'toDelete', 'x')",
            )
            conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (2, 'other', 'x')",
            )
            conn.execute(
                "INSERT INTO radio_stations (id, name, owner_id, created_by) "
                "VALUES (101, 'Owned', 1, 1)",
            )
            conn.execute(
                "INSERT INTO radio_stations (id, name, owner_id, created_by) "
                "VALUES (102, 'CreatedFor', 2, 1)",
            )

    def tearDown(self):
        self.db_patch.stop()
        self.control_db_patch.stop()
        self.temp.cleanup()

    def test_owned_stations_are_deleted_and_created_by_is_cleared(self):
        auth.delete_user(1)
        with db.db() as conn:
            rows = {
                row["id"]: dict(row)
                for row in conn.execute("SELECT id, owner_id, created_by FROM radio_stations")
            }
        self.assertNotIn(101, rows)
        self.assertIn(102, rows)
        self.assertIsNone(rows[102]["created_by"])


if __name__ == "__main__":
    unittest.main()
