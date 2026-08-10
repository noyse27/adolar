import json
import os
import tempfile
import time
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-playlists-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-playlists-import-control.db"),
)

import db
import errors


class PlaylistTestBase(unittest.TestCase):
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

    def _add_track(self, path, **fields):
        fields.setdefault("title", os.path.basename(path))
        columns = ", ".join(["path", *fields.keys()])
        placeholders = ", ".join(["?"] * (1 + len(fields)))
        with db.db() as conn:
            cur = conn.execute(
                f"INSERT INTO tracks ({columns}) VALUES ({placeholders})",
                [path, *fields.values()],
            )
            return cur.lastrowid


class SystemPlaylistSeedTests(PlaylistTestBase):
    def test_get_playlists_includes_the_four_system_playlists(self):
        playlists = db.get_playlists(user_id=1)
        system_sorts = {p["sort"] for p in playlists if p["is_system"] and p["owner_id"] is None}
        self.assertEqual(system_sorts, {"recent", "top_played", "newest_added", "disco_top"})

    def test_get_playlists_also_creates_the_users_favorites_playlist(self):
        playlists = db.get_playlists(user_id=1)
        favorites = [p for p in playlists if p.get("system_key") == "favorites"]
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0]["owner_id"], 1)


class CreatePlaylistTests(PlaylistTestBase):
    def test_create_playlist_rejects_unknown_type(self):
        with self.assertRaises(errors.ValidationError):
            db.create_playlist(1, "Name", "{}", "artist", type_="not-a-type")

    def test_create_playlist_returns_new_id_and_is_visible_to_its_owner(self):
        playlist_id = db.create_playlist(1, "My Smart List", "{}", "artist")
        playlists = db.get_playlists(user_id=1)
        self.assertIn(playlist_id, [p["id"] for p in playlists])

    def test_created_playlist_is_not_visible_to_another_user(self):
        db.create_playlist(1, "Private-ish", "{}", "artist")
        other_playlists = db.get_playlists(user_id=2)
        self.assertNotIn("Private-ish", [p["name"] for p in other_playlists])


class NextPlaylistNameTests(PlaylistTestBase):
    def test_first_default_name_is_number_one(self):
        self.assertEqual(db.next_playlist_name(1), "Neue Playlist 1")

    def test_increments_based_on_existing_default_named_playlists(self):
        db.create_playlist(1, "Neue Playlist 1", "{}", "artist")
        db.create_playlist(1, "Neue Playlist 2", "{}", "artist")
        self.assertEqual(db.next_playlist_name(1), "Neue Playlist 3")

    def test_ignores_gaps_and_uses_the_highest_seen_number(self):
        db.create_playlist(1, "Neue Playlist 5", "{}", "artist")
        self.assertEqual(db.next_playlist_name(1), "Neue Playlist 6")


class PersonalPlaylistCrudTests(PlaylistTestBase):
    def setUp(self):
        super().setUp()
        self.track_a = self._add_track("/music/a.mp3")
        self.track_b = self._add_track("/music/b.mp3")

    def test_save_new_static_playlist_stores_ordered_tracks(self):
        playlist_id = db.save_personal_playlist(
            1, "My Mix", "static", "{}", "artist", [self.track_b, self.track_a],
        )
        with db.db() as conn:
            rows = conn.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id=? ORDER BY added_at",
                (playlist_id,),
            ).fetchall()
        self.assertEqual([r["track_id"] for r in rows], [self.track_b, self.track_a])

    def test_save_rejects_track_ids_that_do_not_exist(self):
        with self.assertRaises(errors.ValidationError):
            db.save_personal_playlist(1, "Broken", "static", "{}", "artist", [999999])

    def test_save_deduplicates_repeated_track_ids(self):
        playlist_id = db.save_personal_playlist(
            1, "Dedup", "static", "{}", "artist", [self.track_a, self.track_a, self.track_a],
        )
        with db.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id=?", (playlist_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_save_rejects_unknown_type(self):
        with self.assertRaises(errors.ValidationError):
            db.save_personal_playlist(1, "X", "not-a-type", "{}", "artist", [])

    def test_updating_an_existing_playlist_replaces_its_tracks(self):
        playlist_id = db.save_personal_playlist(1, "Mix", "static", "{}", "artist", [self.track_a])
        db.save_personal_playlist(
            1, "Mix Renamed", "static", "{}", "artist", [self.track_b], playlist_id=playlist_id,
        )
        updated = db.get_personal_playlist(playlist_id, user_id=1)
        self.assertEqual(updated["name"], "Mix Renamed")
        with db.db() as conn:
            rows = conn.execute(
                "SELECT track_id FROM playlist_tracks WHERE playlist_id=?", (playlist_id,),
            ).fetchall()
        self.assertEqual([r["track_id"] for r in rows], [self.track_b])

    def test_updating_someone_elses_playlist_returns_none(self):
        playlist_id = db.save_personal_playlist(1, "Mine", "static", "{}", "artist", [])
        result = db.save_personal_playlist(
            2, "Hijacked", "static", "{}", "artist", [], playlist_id=playlist_id,
        )
        self.assertIsNone(result)

    def test_get_personal_playlist_does_not_leak_other_users_playlists(self):
        playlist_id = db.save_personal_playlist(1, "Mine", "static", "{}", "artist", [])
        self.assertIsNone(db.get_personal_playlist(playlist_id, user_id=2))
        self.assertIsNotNone(db.get_personal_playlist(playlist_id, user_id=1))

    def test_delete_playlist_only_works_for_the_owner(self):
        playlist_id = db.save_personal_playlist(1, "Mine", "static", "{}", "artist", [])
        self.assertFalse(db.delete_playlist(playlist_id, user_id=2))
        self.assertTrue(db.delete_playlist(playlist_id, user_id=1))
        self.assertIsNone(db.get_personal_playlist(playlist_id, user_id=1))

    def test_system_playlists_cannot_be_deleted(self):
        playlists = db.get_playlists(user_id=1)
        system_playlist = next(p for p in playlists if p["is_system"] and p["owner_id"] is None)
        self.assertFalse(db.delete_playlist(system_playlist["id"], user_id=1))

    def test_rename_playlist_only_works_for_the_owner(self):
        playlist_id = db.save_personal_playlist(1, "Old", "static", "{}", "artist", [])
        self.assertFalse(db.rename_playlist(playlist_id, user_id=2, name="Hacked"))
        self.assertTrue(db.rename_playlist(playlist_id, user_id=1, name="New Name"))
        self.assertEqual(db.get_personal_playlist(playlist_id, user_id=1)["name"], "New Name")


class FavoritesTests(PlaylistTestBase):
    def setUp(self):
        super().setUp()
        self.track_id = self._add_track("/music/a.mp3")

    def test_get_or_create_favorites_is_idempotent(self):
        first = db.get_or_create_favorites(1)
        second = db.get_or_create_favorites(1)
        self.assertEqual(first, second)

    def test_radio_favorites_alias_returns_the_same_playlist(self):
        self.assertEqual(db.get_or_create_radio_favorites(1), db.get_or_create_favorites(1))

    def test_set_favorite_true_then_false_toggles_membership(self):
        self.assertTrue(db.set_favorite(1, self.track_id, True))
        self.assertEqual(db.get_favorite_track_ids(1), {self.track_id})
        self.assertTrue(db.set_favorite(1, self.track_id, False))
        self.assertEqual(db.get_favorite_track_ids(1), set())

    def test_set_favorite_for_missing_track_returns_false(self):
        self.assertFalse(db.set_favorite(1, 999999, True))

    def test_get_favorite_track_ids_can_be_filtered_to_a_subset(self):
        other_track = self._add_track("/music/b.mp3")
        db.set_favorite(1, self.track_id, True)
        db.set_favorite(1, other_track, True)
        self.assertEqual(db.get_favorite_track_ids(1, track_ids=[self.track_id]), {self.track_id})

    def test_favorites_are_per_user(self):
        db.set_favorite(1, self.track_id, True)
        self.assertEqual(db.get_favorite_track_ids(2), set())


class TrackPlaylistMembershipTests(PlaylistTestBase):
    def test_returns_playlist_ids_per_track_excluding_favorites(self):
        track_id = self._add_track("/music/a.mp3")
        db.set_favorite(1, track_id, True)  # should NOT show up as a "membership"
        playlist_id = db.save_personal_playlist(1, "Mix", "static", "{}", "artist", [track_id])

        memberships = db.get_track_playlist_memberships(1, [track_id])
        self.assertEqual(memberships[track_id], [playlist_id])

    def test_empty_track_id_list_returns_empty_dict(self):
        self.assertEqual(db.get_track_playlist_memberships(1, []), {})


class AddTrackToPlaylistTests(PlaylistTestBase):
    def test_adds_and_is_idempotent(self):
        track_id = self._add_track("/music/a.mp3")
        playlist_id = db.save_personal_playlist(1, "Mix", "static", "{}", "artist", [])
        db.add_track_to_playlist(playlist_id, track_id)
        db.add_track_to_playlist(playlist_id, track_id)  # INSERT OR IGNORE
        with db.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id=?", (playlist_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)


class GetPlaylistTracksTests(PlaylistTestBase):
    def setUp(self):
        super().setUp()
        self.track_a = self._add_track("/music/a.mp3", artist="Artist A", album="Album A")
        self.track_b = self._add_track("/music/b.mp3", artist="Artist B", album="Album B")

    def test_static_playlist_returns_tracks_in_added_order_with_formatting(self):
        playlist_id = db.save_personal_playlist(
            1, "Mix", "static", "{}", "artist", [self.track_b, self.track_a],
        )
        tracks = db.get_playlist_tracks(playlist_id, user_id=1)
        self.assertEqual([t["id"] for t in tracks], [self.track_b, self.track_a])
        self.assertEqual(tracks[0]["format"], "MP3")
        self.assertIn("duration_fmt", tracks[0])

    def test_wrong_user_gets_none_for_a_private_playlist(self):
        playlist_id = db.save_personal_playlist(1, "Mine", "static", "{}", "artist", [])
        self.assertIsNone(db.get_playlist_tracks(playlist_id, user_id=2))

    def test_unknown_playlist_returns_none(self):
        self.assertIsNone(db.get_playlist_tracks(999999, user_id=1))

    def test_system_playlist_is_visible_to_any_user(self):
        playlists = db.get_playlists(user_id=1)
        system_playlist = next(p for p in playlists if p["is_system"] and p["owner_id"] is None)
        # Should not raise / return None just because owner_id is NULL and
        # requester isn't the "owner".
        result = db.get_playlist_tracks(system_playlist["id"], user_id=1)
        self.assertIsInstance(result, list)

    def test_newest_added_sort_uses_added_at_not_reindex_time(self):
        with db.db() as conn:
            conn.execute(
                "UPDATE tracks SET added_at=100, indexed_at=300 WHERE id=?",
                (self.track_a,),
            )
            conn.execute(
                "UPDATE tracks SET added_at=200, indexed_at=100 WHERE id=?",
                (self.track_b,),
            )
        _, tracks = db.search_tracks(
            page=1, per_page=100, sort="newest_added", count=False, user_id=1,
        )
        self.assertEqual([track["id"] for track in tracks[:2]], [self.track_b, self.track_a])

    def test_smart_playlist_with_editor_filters_matches_by_rule(self):
        saved = {
            "editor_version": 1,
            "search": {},
            "rules": {"mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "Artist A"}]},
        }
        playlist_id = db.save_personal_playlist(
            1, "Smart", "smart", json.dumps(saved), "artist", [],
        )
        tracks = db.get_playlist_tracks(playlist_id, user_id=1)
        self.assertEqual([t["id"] for t in tracks], [self.track_a])

    def test_legacy_smart_playlist_without_editor_version_falls_back_to_search_tracks(self):
        saved = {"artist_query": "Artist B"}
        playlist_id = db.save_personal_playlist(
            1, "Legacy Smart", "smart", json.dumps(saved), "artist", [],
        )
        tracks = db.get_playlist_tracks(playlist_id, user_id=1)
        self.assertEqual([t["id"] for t in tracks], [self.track_b])


class GetPlaylistFilterTracksTests(PlaylistTestBase):
    def setUp(self):
        super().setUp()
        self.track_a = self._add_track("/music/a.mp3", artist="Zebra", genre="Rock")
        self.track_b = self._add_track("/music/b.mp3", artist="Aardvark", genre="Jazz")

    def test_combines_free_text_search_with_rules(self):
        saved = {
            "search": {"artist": "Zebra"},
            "rules": {"mode": "all", "rules": []},
        }
        tracks = db.get_playlist_filter_tracks(saved, user_id=1)
        self.assertEqual([t["id"] for t in tracks], [self.track_a])

    def test_excludes_ids_are_honored(self):
        saved = {"search": {}, "rules": {"mode": "all", "rules": []}}
        tracks = db.get_playlist_filter_tracks(saved, user_id=1, exclude_ids=[self.track_a])
        self.assertNotIn(self.track_a, [t["id"] for t in tracks])
        self.assertIn(self.track_b, [t["id"] for t in tracks])

    def test_sort_order_is_applied(self):
        saved = {"search": {}, "rules": {"mode": "all", "rules": []}}
        tracks = db.get_playlist_filter_tracks(saved, user_id=1, sort="artist")
        self.assertEqual([t["artist"] for t in tracks], ["Aardvark", "Zebra"])

    def test_added_before_only_returns_tracks_older_than_the_period(self):
        with db.db() as conn:
            conn.execute(
                "UPDATE tracks SET added_at=? WHERE id=?",
                (time.time() - 10 * 86400, self.track_a),
            )
            conn.execute(
                "UPDATE tracks SET added_at=? WHERE id=?",
                (time.time() - 2 * 86400, self.track_b),
            )
        saved = {
            "search": {},
            "rules": {"mode": "all", "rules": [
                {"field": "added", "op": "before", "value": 7, "unit": "days"},
            ]},
        }
        tracks = db.get_playlist_filter_tracks(saved, user_id=1)
        self.assertEqual([track["id"] for track in tracks], [self.track_a])

    def test_added_within_last_only_returns_recent_tracks(self):
        with db.db() as conn:
            conn.execute(
                "UPDATE tracks SET added_at=? WHERE id=?",
                (time.time() - 100 * 86400, self.track_a),
            )
            conn.execute(
                "UPDATE tracks SET added_at=? WHERE id=?",
                (time.time() - 20 * 86400, self.track_b),
            )
        saved = {
            "search": {},
            "rules": {"mode": "all", "rules": [
                {"field": "added", "op": "within_last", "value": 2, "unit": "months"},
            ]},
        }
        tracks = db.get_playlist_filter_tracks(saved, user_id=1)
        self.assertEqual([track["id"] for track in tracks], [self.track_b])


if __name__ == "__main__":
    unittest.main()
