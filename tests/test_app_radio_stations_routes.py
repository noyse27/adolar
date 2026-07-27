import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-radioroutes-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-radioroutes-import-control.db"),
)

import app as app_module
import db


class RadioStationsRouteTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jingle_root = os.path.join(self.temp.name, "jingles")
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
            mock.patch.object(
                app_module, "LIBRARY_REGISTRY_PATH",
                os.path.join(self.temp.name, "libraries.json"),
            ),
            mock.patch.object(app_module, "JINGLE_ROOT", self.jingle_root),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _login(self, role="user"):
        user = {
            "id": 1, "username": "u", "role": role, "allow_download": 0,
            "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
            "is_active": 1, "must_change_password": 0,
        }
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user), \
            mock.patch.object(app_module.db, "get_setting", return_value="1")


class ListRadioStationsRouteTests(RadioStationsRouteTestBase):
    def test_anonymous_can_list_global_stations_without_login(self):
        response = self.client.get("/api/radio-stations")
        self.assertEqual(response.status_code, 200)
        names = {s["name"] for s in response.get_json()}
        self.assertIn("Adolar Radio", names)

    def test_private_stations_hidden_from_other_users(self):
        db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        login, setting = self._login()
        with login, setting:
            self.client.set_cookie("adolar_session", "token")
            with mock.patch.object(
                app_module._auth, "get_user_by_token",
                return_value={
                    "id": 2, "username": "other", "role": "user", "allow_download": 0,
                    "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
                    "is_active": 1, "must_change_password": 0,
                },
            ):
                response = self.client.get("/api/radio-stations")
        names = {s["name"] for s in response.get_json()}
        self.assertNotIn("Mine", names)

    def test_admin_flag_reveals_all_private_stations(self):
        db.create_radio_station("Someones", "", {}, user_id=2, scope="private")
        login, setting = self._login(role="admin")
        with login, setting:
            response = self.client.get("/api/radio-stations?admin=1")
        names = {s["name"] for s in response.get_json()}
        self.assertIn("Someones", names)

    def test_adolar4u_station_hidden_when_not_available_to_the_user(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.get("/api/radio-stations")
        names = {s["name"] for s in response.get_json()}
        self.assertNotIn("Adolar4U", names)


class CreateRadioStationRouteTests(RadioStationsRouteTestBase):
    def test_requires_capability(self):
        login, _ = self._login()
        with login, mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.post("/api/radio-stations", json={"name": "X"})
        self.assertEqual(response.status_code, 403)

    def test_requires_a_name(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post("/api/radio-stations", json={"name": "  "})
        self.assertEqual(response.status_code, 400)

    def test_non_admin_is_forced_into_private_scope(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post(
                "/api/radio-stations", json={"name": "Mine", "scope": "global"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["scope"], "private")

    def test_admin_can_create_a_global_station(self):
        login, setting = self._login(role="admin")
        with login, setting:
            response = self.client.post(
                "/api/radio-stations", json={"name": "Global", "scope": "global"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["scope"], "global")

    def test_duplicate_name_returns_409(self):
        db.create_radio_station("Dup", "", {}, user_id=1, scope="global")
        login, setting = self._login(role="admin")
        with login, setting:
            response = self.client.post(
                "/api/radio-stations", json={"name": "Dup", "scope": "global"},
            )
        self.assertEqual(response.status_code, 409)

    def test_invalid_filter_returns_400(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post("/api/radio-stations", json={
                "name": "Bad", "filter": {"mode": "all", "rules": [{"field": "nope", "op": "eq", "value": 1}]},
            })
        self.assertEqual(response.status_code, 400)


class UpdateRadioStationRouteTests(RadioStationsRouteTestBase):
    def test_requires_capability(self):
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        login, _ = self._login()
        with login, mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.put(f"/api/radio-stations/{station_id}", json={"name": "New"})
        self.assertEqual(response.status_code, 403)

    def test_requires_a_name(self):
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        login, setting = self._login()
        with login, setting:
            response = self.client.put(f"/api/radio-stations/{station_id}", json={"name": ""})
        self.assertEqual(response.status_code, 400)

    def test_updating_a_missing_station_returns_404(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.put("/api/radio-stations/999999", json={"name": "New"})
        self.assertEqual(response.status_code, 404)

    def test_owner_can_update_their_station(self):
        station_id = db.create_radio_station("Old", "", {}, user_id=1, scope="private")
        login, setting = self._login()
        with login, setting:
            response = self.client.put(f"/api/radio-stations/{station_id}", json={"name": "New"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "New")


class DeleteRadioStationRouteTests(RadioStationsRouteTestBase):
    def test_requires_capability(self):
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        login, _ = self._login()
        with login, mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.delete(f"/api/radio-stations/{station_id}")
        self.assertEqual(response.status_code, 403)

    def test_deleting_missing_station_returns_404(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.delete("/api/radio-stations/999999")
        self.assertEqual(response.status_code, 404)

    def test_owner_can_delete_their_station(self):
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        login, setting = self._login()
        with login, setting:
            response = self.client.delete(f"/api/radio-stations/{station_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db.get_radio_station(station_id))


class TestRadioStationFilterRouteTests(RadioStationsRouteTestBase):
    def test_requires_admin(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post("/api/radio-stations/test", json={"filter": {}})
        self.assertEqual(response.status_code, 403)

    def test_returns_matching_tracks(self):
        with db.db() as conn:
            conn.execute("INSERT INTO tracks (path, title, artist) VALUES ('/a.mp3', 'A', 'Zebra')")
        login, setting = self._login(role="admin")
        with login, setting:
            response = self.client.post("/api/radio-stations/test", json={
                "filter": {"mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "Zebra"}]},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total"], 1)

    def test_invalid_filter_returns_400(self):
        login, setting = self._login(role="admin")
        with login, setting:
            response = self.client.post("/api/radio-stations/test", json={
                "filter": {"mode": "all", "rules": [{"field": "nope", "op": "eq", "value": 1}]},
            })
        self.assertEqual(response.status_code, 400)


class RadioStationJingleRouteTests(RadioStationsRouteTestBase):
    def setUp(self):
        super().setUp()
        self.station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")

    def test_upload_requires_capability(self):
        login, _ = self._login()
        with login, mock.patch.object(app_module.db, "get_setting", return_value="0"):
            response = self.client.post(f"/api/radio-stations/{self.station_id}/jingle")
        self.assertEqual(response.status_code, 403)

    def test_upload_requires_a_file(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post(f"/api/radio-stations/{self.station_id}/jingle")
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_unsupported_extension(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post(
                f"/api/radio-stations/{self.station_id}/jingle",
                data={"file": (__import__("io").BytesIO(b"data"), "jingle.txt")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 400)

    def test_upload_stores_the_file_and_enables_the_jingle(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.post(
                f"/api/radio-stations/{self.station_id}/jingle",
                data={"file": (__import__("io").BytesIO(b"audio-data"), "jingle.mp3"), "every": "10"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["has_jingle"])
        self.assertTrue(data["jingle_enabled"])
        self.assertEqual(data["jingle_every_tracks"], 10)

    def test_patch_settings_requires_existing_station(self):
        login, setting = self._login()
        with login, setting:
            response = self.client.patch(
                "/api/radio-stations/999999/jingle", json={"every": 5, "enabled": True},
            )
        self.assertEqual(response.status_code, 404)

    def test_patch_settings_updates_interval(self):
        db.set_radio_station_jingle(self.station_id, "/some/path.mp3", 5, True)
        login, setting = self._login()
        with login, setting:
            response = self.client.patch(
                f"/api/radio-stations/{self.station_id}/jingle", json={"every": 20, "enabled": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["jingle_every_tracks"], 20)

    def test_delete_clears_the_jingle(self):
        login, setting = self._login()
        with login, setting:
            self.client.post(
                f"/api/radio-stations/{self.station_id}/jingle",
                data={"file": (__import__("io").BytesIO(b"audio-data"), "jingle.mp3")},
                content_type="multipart/form-data",
            )
            response = self.client.delete(f"/api/radio-stations/{self.station_id}/jingle")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["has_jingle"])

    def test_stream_missing_jingle_returns_404(self):
        response = self.client.get(f"/api/radio-stations/{self.station_id}/jingle")
        self.assertEqual(response.status_code, 404)

    def test_stream_serves_the_uploaded_jingle_file(self):
        login, setting = self._login()
        with login, setting:
            self.client.post(
                f"/api/radio-stations/{self.station_id}/jingle",
                data={"file": (__import__("io").BytesIO(b"audio-data"), "jingle.mp3")},
                content_type="multipart/form-data",
            )
        response = self.client.get(f"/api/radio-stations/{self.station_id}/jingle")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"audio-data")


class RadioStationTracksRouteTests(RadioStationsRouteTestBase):
    def test_missing_station_returns_404(self):
        response = self.client.get("/api/radio-stations/999999/tracks")
        self.assertEqual(response.status_code, 404)

    def test_returns_tracks_and_shuffle_session_header(self):
        with db.db() as conn:
            conn.execute("INSERT INTO tracks (path, title) VALUES ('/a.mp3', 'A')")
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="global")
        response = self.client.get(f"/api/radio-stations/{station_id}/tracks")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Shuffle-Session", response.headers)
        self.assertEqual(len(response.get_json()), 1)


if __name__ == "__main__":
    unittest.main()
