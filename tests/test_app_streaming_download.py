import io
import os
import tempfile
import unittest
import zipfile
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-stream-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-stream-import-control.db"),
)

import app as app_module


def _make_png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class StreamingTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music_root = os.path.join(self.temp.name, "music")
        os.makedirs(self.music_root)
        self.thumb_dir = os.path.join(self.temp.name, "thumbs")
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "adolar.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
            mock.patch.object(app_module, "MUSIC_ROOT", self.music_root),
            mock.patch.object(
                app_module, "LIBRARY_REGISTRY_PATH",
                os.path.join(self.temp.name, "libraries.json"),
            ),
            mock.patch.object(app_module, "_THUMB_DIR", self.thumb_dir),
        ]
        for p in self.patches:
            p.start()
        app_module.db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def _write_track_file(self, relative_path, content=b"fake audio bytes"):
        full_path = os.path.join(self.music_root, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)
        return full_path


class SafePathTests(StreamingTestBase):
    def test_relative_path_resolves_under_music_root(self):
        self._write_track_file("song.mp3")
        resolved = app_module._safe_path("song.mp3")
        self.assertEqual(resolved, os.path.realpath(os.path.join(self.music_root, "song.mp3")))

    def test_traversal_outside_music_root_is_rejected(self):
        self.assertIsNone(app_module._safe_path("../../etc/passwd"))

    def test_absolute_path_outside_music_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = os.path.join(outside_dir, "outside.mp3")
            self.assertIsNone(app_module._safe_path(outside))


class CoverRouteTests(StreamingTestBase):
    def test_missing_cover_returns_404(self):
        response = self.client.get("/api/cover/no-such-hash")
        self.assertEqual(response.status_code, 404)

    def test_existing_cover_generates_and_serves_a_thumbnail(self):
        app_module.db.save_cover("abc123", _make_png_bytes(), "image/png")
        response = self.client.get("/api/cover/abc123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/webp")
        self.assertTrue(os.path.exists(os.path.join(self.thumb_dir, "abc123.webp")))

    def test_second_request_serves_the_cached_thumbnail_file_directly(self):
        app_module.db.save_cover("abc123", _make_png_bytes(), "image/png")
        self.client.get("/api/cover/abc123")
        with mock.patch.object(app_module.db, "get_cover") as mocked_get_cover:
            response = self.client.get("/api/cover/abc123")
        self.assertEqual(response.status_code, 200)
        mocked_get_cover.assert_not_called()

    def test_full_query_param_returns_the_original_image_not_a_thumbnail(self):
        app_module.db.save_cover("abc123", _make_png_bytes(), "image/png")
        response = self.client.get("/api/cover/abc123?full=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")


class StreamRouteTests(StreamingTestBase):
    def setUp(self):
        super().setUp()
        self.content = b"0123456789" * 10  # 100 bytes
        self._write_track_file("song.mp3", self.content)
        with app_module.db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path, title) VALUES ('song.mp3', 'Song')")
            self.track_id = cur.lastrowid

    def test_missing_track_id_returns_404(self):
        self.assertEqual(self.client.get("/api/stream/999999").status_code, 404)

    def test_track_whose_file_is_gone_returns_404(self):
        with app_module.db.db() as conn:
            cur = conn.execute("INSERT INTO tracks (path, title) VALUES ('missing.mp3', 'Gone')")
            missing_id = cur.lastrowid
        self.assertEqual(self.client.get(f"/api/stream/{missing_id}").status_code, 404)

    def test_full_request_without_range_returns_200_with_full_body(self):
        response = self.client.get(f"/api/stream/{self.track_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.content)

    def test_range_request_returns_206_with_correct_partial_content(self):
        response = self.client.get(
            f"/api/stream/{self.track_id}", headers={"Range": "bytes=10-19"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, self.content[10:20])
        self.assertEqual(response.headers["Content-Range"], "bytes 10-19/100")

    def test_open_ended_range_streams_to_the_end_of_file(self):
        response = self.client.get(
            f"/api/stream/{self.track_id}", headers={"Range": "bytes=90-"},
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, self.content[90:])

    def test_out_of_bounds_range_returns_416(self):
        response = self.client.get(
            f"/api/stream/{self.track_id}", headers={"Range": "bytes=1000-2000"},
        )
        self.assertEqual(response.status_code, 416)

    def test_content_type_is_derived_from_extension(self):
        response = self.client.get(f"/api/stream/{self.track_id}")
        self.assertEqual(response.mimetype, "audio/mpeg")


class DownloadRouteTests(StreamingTestBase):
    def setUp(self):
        super().setUp()
        self._write_track_file("a.mp3", b"audio-a")
        self._write_track_file("b.mp3", b"audio-b")
        with app_module.db.db() as conn:
            self.track_a = conn.execute(
                "INSERT INTO tracks (path, title, artist) VALUES ('a.mp3', 'A', 'Artist')",
            ).lastrowid
            self.track_b = conn.execute(
                "INSERT INTO tracks (path, title, artist) VALUES ('b.mp3', 'B', 'Artist')",
            ).lastrowid

    def _as_downloader(self):
        user = {
            "id": 1, "username": "u", "role": "user", "allow_download": 1,
            "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
            "is_active": 1, "must_change_password": 0,
        }
        self.client.set_cookie("adolar_session", "token")
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user)

    def test_anonymous_request_is_blocked_by_auth_middleware(self):
        response = self.client.post("/api/download", json={"ids": [self.track_a]})
        self.assertEqual(response.status_code, 401)

    def test_logged_in_user_without_download_capability_is_forbidden(self):
        user = {
            "id": 1, "username": "u", "role": "user", "allow_download": 0,
            "allow_playlists": 1, "allow_radio_stations": 1, "contributes_playcount": 0,
            "is_active": 1, "must_change_password": 0,
        }
        self.client.set_cookie("adolar_session", "token")
        with mock.patch.object(app_module._auth, "get_user_by_token", return_value=user):
            response = self.client.post("/api/download", json={"ids": [self.track_a]})
        self.assertEqual(response.status_code, 403)

    def test_rejects_empty_id_list(self):
        with self._as_downloader():
            response = self.client.post("/api/download", json={"ids": []})
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_numeric_ids(self):
        with self._as_downloader():
            response = self.client.post("/api/download", json={"ids": ["not-a-number"]})
        self.assertEqual(response.status_code, 400)

    def test_rejects_too_many_ids(self):
        with self._as_downloader(), mock.patch.object(app_module, "MAX_DOWNLOAD_IDS", 1):
            response = self.client.post("/api/download", json={"ids": [self.track_a, self.track_b]})
        self.assertEqual(response.status_code, 400)

    def test_builds_a_zip_with_the_requested_tracks(self):
        with self._as_downloader():
            response = self.client.post("/api/download", json={"ids": [self.track_a, self.track_b]})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 2)
        self.assertTrue(any("A.mp3" in n for n in names))

    def test_silently_skips_tracks_whose_files_are_missing(self):
        with app_module.db.db() as conn:
            missing_id = conn.execute(
                "INSERT INTO tracks (path, title, artist) VALUES ('missing.mp3', 'M', 'Artist')",
            ).lastrowid
        with self._as_downloader():
            response = self.client.post(
                "/api/download", json={"ids": [self.track_a, missing_id]},
            )
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as zf:
            names = zf.namelist()
        self.assertEqual(len(names), 1)


if __name__ == "__main__":
    unittest.main()
