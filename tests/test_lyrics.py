import json
import os
import tempfile
import time
import unittest
from unittest import mock

from mutagen.id3 import ID3, TIT2, TPE1

_import_temp = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp.name, "lyrics-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp.name, "lyrics-import-control.db"),
)

import app as app_module
import auth
import db
import lyrics


def make_mp3(path: str, title="Song", artist="Artist") -> None:
    header = bytes([0xFF, 0xFB, 0x90, 0xC4])
    frame_size = 144 * 128000 // 44100
    frame = header + bytes(frame_size - len(header))
    with open(path, "wb") as handle:
        for _ in range(50):
            handle.write(frame)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.save(path)


class LyricsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music = os.path.join(self.temp.name, "music")
        os.makedirs(self.music)
        self.path = os.path.join(self.music, "track.mp3")
        make_mp3(self.path)
        self.patches = [
            mock.patch.object(db, "DB_PATH", os.path.join(self.temp.name, "content.db")),
            mock.patch.object(db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db")),
        ]
        for patch in self.patches:
            patch.start()
        db.init_db()
        db.upsert_track({
            "path": self.path,
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "album_artist": "Artist",
            "genre": "Pop",
            "year": 2024,
            "track_no": 1,
            "duration": 1,
            "bitrate": 128,
            "size": os.path.getsize(self.path),
            "cover_hash": None,
            "bpm": None,
            "mtime": os.path.getmtime(self.path),
            "play_count": 0,
            "loved": False,
        })
        with db.db() as conn:
            self.track_id = conn.execute("SELECT id FROM tracks").fetchone()["id"]

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def test_every_track_gets_pending_row(self):
        row = lyrics.get_track_lyrics(self.track_id)
        self.assertEqual(row["status"], "pending")
        self.assertFalse(row["available"])

    def test_track_icon_availability_respects_admin_switch(self):
        lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Words", ""), source="tag",
        )
        disabled = [{"id": self.track_id}]
        db._annotate_lyrics_availability(disabled)
        self.assertFalse(disabled[0]["has_lyrics"])

        db.set_setting("lyrics_enabled", "1")
        enabled = [{"id": self.track_id}]
        db._annotate_lyrics_availability(enabled)
        self.assertTrue(enabled[0]["has_lyrics"])

    def test_lrc_parser_returns_plain_and_sorted_timed_lines(self):
        raw = "[ar:Artist]\n[00:03.50]Second\n[00:01.00]First"
        self.assertEqual(lyrics.lrc_to_plain(raw), "Second\nFirst")
        self.assertEqual(
            lyrics.lrc_lines(raw),
            [
                {"time_ms": 1000, "text": "First"},
                {"time_ms": 3500, "text": "Second"},
            ],
        )

    def test_sidecar_takes_priority_over_embedded_tag(self):
        lyrics.write_mp3_tags(self.path, "Embedded", "")
        with open(os.path.splitext(self.path)[0] + ".lrc", "w", encoding="utf-8") as handle:
            handle.write("[00:01.00]Sidecar")
        result, source = lyrics.read_local(self.path)
        self.assertEqual(source, "sidecar")
        self.assertEqual(result.plain, "Sidecar")

    def test_mp3_plain_and_synced_lyrics_round_trip(self):
        synced = "[00:01.00]First\n[00:02.50]Second"
        lyrics.write_mp3_tags(self.path, "First\nSecond", synced)
        result = lyrics.read_mp3_tags(self.path)
        self.assertEqual(result.plain, "First\nSecond")
        self.assertEqual(lyrics.lrc_lines(result.synced), lyrics.lrc_lines(synced))

    def test_resolve_local_tag_does_not_call_provider(self):
        lyrics.write_mp3_tags(self.path, "Local words", "")
        with mock.patch.object(lyrics, "fetch_lrclib") as provider:
            result = lyrics.resolve_track(self.track_id)
        provider.assert_not_called()
        self.assertEqual(result["source"], "tag")
        self.assertTrue(result["available"])

    def test_manual_provider_search_returns_multiple_candidates_without_replacing(self):
        original = lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Wrong local words", ""), source="tag",
        )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps([
            {
                "id": 77, "trackName": "Song", "artistName": "Artist",
                "albumName": "Album", "duration": 61, "syncedLyrics": "[00:01]One",
            },
            {
                "id": 78, "trackName": "Song (Live)", "artistName": "Artist",
                "albumName": "Live", "duration": 74, "plainLyrics": "Two",
            },
        ]).encode()

        with mock.patch.object(lyrics.urllib.request, "urlopen", return_value=response):
            results = lyrics.search_provider_candidates(self.track_id)

        self.assertEqual([result["id"] for result in results], ["77", "78"])
        self.assertTrue(results[0]["synced"])
        current = lyrics.get_track_lyrics(self.track_id)
        self.assertEqual(current["plain_lyrics"], "Wrong local words")
        self.assertEqual(current["revision"], original["revision"])

    def test_selected_provider_candidate_replaces_wrong_local_lyrics(self):
        lyrics.write_mp3_tags(self.path, "Wrong local words", "")
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({
            "id": 77,
            "plainLyrics": "Correct provider words",
            "syncedLyrics": None,
            "instrumental": False,
        }).encode()

        with mock.patch.object(lyrics.urllib.request, "urlopen", return_value=response):
            result = lyrics.apply_provider_candidate(self.track_id, "77")

        self.assertEqual(result["plain_lyrics"], "Correct provider words")
        self.assertEqual(result["source"], "lrclib")
        self.assertEqual(lyrics.read_mp3_tags(self.path).plain, "Correct provider words")

    def test_selected_provider_candidate_rejects_invalid_id(self):
        with self.assertRaises(lyrics.LyricsValidationError):
            lyrics.apply_provider_candidate(self.track_id, "../wrong")

    def test_provider_result_is_saved_to_db_tag_and_sidecar(self):
        db.set_setting("lyrics_enabled", "1")
        provider_result = lyrics.ProviderResult(
            plain="First\nSecond",
            synced="[00:01.00]First\n[00:02.00]Second",
            source_id="123",
        )
        with mock.patch.object(lyrics, "fetch_lrclib", return_value=provider_result):
            result = lyrics.resolve_track(self.track_id)
        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "lrclib")
        self.assertEqual(result["source_id"], "123")
        self.assertTrue(os.path.isfile(os.path.splitext(self.path)[0] + ".lrc"))
        self.assertEqual(lyrics.read_mp3_tags(self.path).plain, "First\nSecond")

    def test_missing_result_is_cached_for_four_weeks(self):
        db.set_setting("lyrics_enabled", "1")
        with mock.patch.object(lyrics, "fetch_lrclib", return_value=None) as provider:
            first = lyrics.resolve_track(self.track_id)
            second = lyrics.resolve_track(self.track_id)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first["status"], "missing")
        self.assertGreater(first["next_check_at"], time.time() + 27 * 24 * 3600)
        self.assertEqual(second["status"], "missing")

    def test_file_change_resets_existing_lyrics_state_to_pending(self):
        lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Words", ""), source="tag",
        )
        with db.db() as conn:
            original = dict(conn.execute("SELECT * FROM tracks").fetchone())
        original.update({"mtime": original["mtime"] + 5})
        db.upsert_track(original)
        self.assertEqual(lyrics.get_track_lyrics(self.track_id)["status"], "pending")

    def test_user_update_checks_revision_and_writes_files(self):
        current = lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Old", ""), source="tag",
        )
        updated = lyrics.update_track_lyrics(
            self.track_id,
            content="[00:01.00]New",
            format_="lrc",
            expected_revision=current["revision"],
            user_id=9,
        )
        self.assertEqual(updated["source"], "user")
        self.assertEqual(updated["plain_lyrics"], "New")
        with self.assertRaises(lyrics.LyricsConflict):
            lyrics.update_track_lyrics(
                self.track_id,
                content="Stale",
                format_="plain",
                expected_revision=current["revision"],
                user_id=9,
            )


class LyricsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.music = os.path.join(self.temp.name, "music")
        os.makedirs(self.music)
        self.path = os.path.join(self.music, "track.mp3")
        make_mp3(self.path)
        self.patches = [
            mock.patch.object(app_module.db, "DB_PATH", os.path.join(self.temp.name, "content.db")),
            mock.patch.object(
                app_module.db, "CONTROL_DB_PATH", os.path.join(self.temp.name, "control.db"),
            ),
            mock.patch.object(
                app_module, "LIBRARY_REGISTRY_PATH", os.path.join(self.temp.name, "libraries.json"),
            ),
        ]
        for patch in self.patches:
            patch.start()
        app_module.db.init_db()
        app_module.db.upsert_track({
            "path": self.path, "title": "Song", "artist": "Artist", "album": "Album",
            "album_artist": "Artist", "genre": "Pop", "year": 2024, "track_no": 1,
            "duration": 1, "bitrate": 128, "size": os.path.getsize(self.path),
            "cover_hash": None, "bpm": None, "mtime": os.path.getmtime(self.path),
            "play_count": 0, "loved": False,
        })
        with app_module.db.db() as conn:
            self.track_id = conn.execute("SELECT id FROM tracks").fetchone()["id"]
        self.admin_id = auth.create_user("admin", "password123", role="admin")
        self.user_id = auth.create_user("editor", "password123", role="user")
        self.client = app_module.app.test_client()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp.cleanup()

    def login_as(self, user_id):
        user = dict(auth.get_user_by_id(user_id), must_change_password=0)
        return mock.patch.object(app_module._auth, "get_user_by_token", return_value=user)

    def test_get_returns_availability_and_edit_permission(self):
        app_module.db.set_setting("lyrics_enabled", "1")
        lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Words", ""), source="tag",
        )
        auth.set_user_capability(self.user_id, "lyrics_edit", True)
        self.client.set_cookie("adolar_session", "token")
        with self.login_as(self.user_id):
            response = self.client.get(f"/api/tracks/{self.track_id}/lyrics")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["available"])
        self.assertTrue(response.get_json()["editable"])

    def test_put_requires_permission(self):
        app_module.db.set_setting("lyrics_enabled", "1")
        current = lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Old", ""), source="tag",
        )
        self.client.set_cookie("adolar_session", "token")
        with self.login_as(self.user_id):
            denied = self.client.put(
                f"/api/tracks/{self.track_id}/lyrics",
                json={"content": "New", "format": "plain", "revision": current["revision"]},
            )
        self.assertEqual(denied.status_code, 403)

        auth.set_user_capability(self.user_id, "lyrics_edit", True)
        with self.login_as(self.user_id):
            allowed = self.client.put(
                f"/api/tracks/{self.track_id}/lyrics",
                json={"content": "New", "format": "plain", "revision": current["revision"]},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["plain_lyrics"], "New")

    def test_manual_search_requires_edit_permission_and_returns_candidates(self):
        app_module.db.set_setting("lyrics_enabled", "1")
        candidates = [{
            "id": "88", "title": "Song", "artist": "Artist", "album": "Album",
            "duration": 60, "synced": True, "instrumental": False,
        }]
        self.client.set_cookie("adolar_session", "token")

        with self.login_as(self.user_id):
            denied = self.client.post(f"/api/tracks/{self.track_id}/lyrics/search")
        self.assertEqual(denied.status_code, 403)

        auth.set_user_capability(self.user_id, "lyrics_edit", True)
        with self.login_as(self.user_id), mock.patch.object(
            lyrics, "search_provider_candidates", return_value=candidates,
        ):
            allowed = self.client.post(f"/api/tracks/{self.track_id}/lyrics/search")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["results"], candidates)

    def test_manual_search_without_match_keeps_current_lyrics(self):
        app_module.db.set_setting("lyrics_enabled", "1")
        auth.set_user_capability(self.user_id, "lyrics_edit", True)
        lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Existing words", ""), source="tag",
        )
        self.client.set_cookie("adolar_session", "token")

        with self.login_as(self.user_id), mock.patch.object(
            lyrics, "search_provider_candidates", return_value=[],
        ):
            response = self.client.post(f"/api/tracks/{self.track_id}/lyrics/search")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"], [])
        self.assertEqual(
            lyrics.get_track_lyrics(self.track_id)["plain_lyrics"],
            "Existing words",
        )

    def test_selected_search_result_is_persisted(self):
        app_module.db.set_setting("lyrics_enabled", "1")
        auth.set_user_capability(self.user_id, "lyrics_edit", True)
        selected = lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Selected words", ""), source="lrclib",
            source_id="88",
        )
        self.client.set_cookie("adolar_session", "token")

        with self.login_as(self.user_id), mock.patch.object(
            lyrics, "apply_provider_candidate", return_value=selected,
        ) as apply_candidate:
            response = self.client.post(
                f"/api/tracks/{self.track_id}/lyrics/select",
                json={"source_id": "88"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["plain_lyrics"], "Selected words")
        apply_candidate.assert_called_once_with(self.track_id, "88")

    def test_disabled_module_hides_cached_lyrics(self):
        lyrics._store_result(
            self.track_id, lyrics.ProviderResult("Nicht öffentlich", ""), source="tag",
        )

        response = self.client.get(f"/api/tracks/{self.track_id}/lyrics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["plain_lyrics"], "")

    def test_admin_settings_never_return_api_key(self):
        self.client.set_cookie("adolar_session", "token")
        with self.login_as(self.admin_id), mock.patch.object(
            app_module, "_start_lyrics_scan", return_value=True,
        ):
            response = self.client.put(
                "/api/admin/lyrics/settings",
                json={
                    "enabled": True,
                    "provider": "lrclib",
                    "provider_url": "https://lrclib.net",
                    "api_key": "secret-value",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["api_key_configured"])
        self.assertNotIn("api_key", payload)


if __name__ == "__main__":
    unittest.main()
