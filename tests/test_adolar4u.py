import os
import csv
import io
import json
import sqlite3
import tempfile
import unittest
import random
import zipfile
from unittest import mock


_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_temp_dir.name, "adolar4u-test.db"))

import adolar4u
import adolar4u.recommender as recommender
import app as app_module


class Adolar4UTests(unittest.TestCase):
    USER_ID = 21
    TRACK_ID = 401

    def setUp(self):
        app_module.db.init_db()
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (?, 'a4u-listener', 'unused', 'user', 0)
            """, (self.USER_ID,))
            conn.execute("""
                INSERT OR IGNORE INTO tracks (id, path, title, artist, album, genre)
                VALUES (?, 'a4u-test.mp3', 'Signal', 'Listener', 'Tests', 'Electronic')
            """, (self.TRACK_ID,))
            conn.execute("DELETE FROM adolar4u_listening_events WHERE user_id IN (?, 22)", (self.USER_ID,))
            conn.execute("DELETE FROM adolar4u_recommendation_batches WHERE user_id IN (?, 22)", (self.USER_ID,))
            conn.execute("DELETE FROM adolar4u_user_settings WHERE user_id IN (?, 22)", (self.USER_ID,))
            conn.execute("DELETE FROM adolar4u_seed_preferences WHERE user_id IN (?, 22)", (self.USER_ID,))
            conn.execute("DELETE FROM user_play_counts WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM user_lastfm_accounts WHERE user_id=?", (self.USER_ID,))
            conn.execute("DELETE FROM playlists WHERE owner_id=?", (self.USER_ID,))
        adolar4u.update_global_settings({
            "enabled": False,
            "audio_analysis": False,
            "collaborative": False,
        })
        self.user = {
            "id": self.USER_ID,
            "username": "a4u-listener",
            "role": "user",
            "allow_download": 0,
            "allow_playlists": 1,
            "allow_radio_stations": 1,
            "contributes_playcount": 0,
            "is_active": 1,
            "must_change_password": 0,
        }
        self.client = app_module.app.test_client()
        self.client.set_cookie("adolar_session", "adolar4u-test-token")

    def _login(self, user=None):
        return mock.patch.object(
            app_module._auth, "get_user_by_token", return_value=user or self.user,
        )

    def test_event_collection_requires_global_and_personal_opt_in(self):
        with self._login():
            disabled = self.client.post(
                f"/api/adolar4u/events/{self.TRACK_ID}",
                json={"event_type": "started"},
            )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.get_json()["reason"], "module_disabled")

        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        with self._login():
            accepted = self.client.post(
                f"/api/adolar4u/events/{self.TRACK_ID}",
                json={
                    "event_type": "skipped",
                    "position_seconds": 12,
                    "duration_seconds": 240,
                    "source": "radio",
                    "reason": "manual_next",
                    "client_event_id": "skip-1",
                },
            )
        self.assertEqual(accepted.status_code, 202)
        self.assertTrue(accepted.get_json()["accepted"])
        with app_module.db.db() as conn:
            event = conn.execute("""
                SELECT event_type, completion_ratio, source, reason
                FROM adolar4u_listening_events WHERE user_id=?
            """, (self.USER_ID,)).fetchone()
        self.assertEqual(event["event_type"], "skipped")
        self.assertAlmostEqual(event["completion_ratio"], 0.05)
        self.assertEqual(event["source"], "radio")
        self.assertEqual(event["reason"], "manual_next")

    def test_learning_pause_stops_collection_without_disabling_profile(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "learning_paused": True,
        })
        result = adolar4u.record_event(
            self.USER_ID, self.TRACK_ID, {"event_type": "started"},
        )
        self.assertEqual(result["reason"], "learning_paused")

    def test_new_profile_uses_forty_percent_discovery(self):
        settings = adolar4u.get_user_settings(self.USER_ID)
        self.assertEqual(settings["discovery_level"], 0.40)

    def test_duplicate_client_event_is_idempotent(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        event = {"event_type": "completed", "client_event_id": "complete-1"}
        self.assertTrue(adolar4u.record_event(self.USER_ID, self.TRACK_ID, event)["accepted"])
        duplicate = adolar4u.record_event(self.USER_ID, self.TRACK_ID, event)
        self.assertFalse(duplicate["accepted"])
        self.assertTrue(duplicate["duplicate"])

    def test_user_can_delete_personal_learning_history(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        adolar4u.record_event(
            self.USER_ID, self.TRACK_ID, {"event_type": "started"},
        )
        adolar4u.recommend_tracks(self.USER_ID, count=1, rng=random.Random(4))
        with self._login():
            response = self.client.delete("/api/adolar4u/profile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_events"], 1)
        with app_module.db.db() as conn:
            batches = conn.execute(
                "SELECT COUNT(*) FROM adolar4u_recommendation_batches WHERE user_id=?",
                (self.USER_ID,),
            ).fetchone()[0]
        self.assertEqual(batches, 0)

    def test_global_settings_require_admin(self):
        with self._login():
            denied = self.client.put(
                "/api/admin/adolar4u/settings", json={"enabled": True},
            )
        self.assertEqual(denied.status_code, 403)

        admin = {**self.user, "role": "admin"}
        with self._login(admin):
            allowed = self.client.put(
                "/api/admin/adolar4u/settings", json={"enabled": True},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.get_json()["enabled"])

    def test_station_is_visible_only_after_both_opt_ins(self):
        with self._login():
            hidden = self.client.get("/api/radio-stations").get_json()
        self.assertNotIn("Adolar4U", [station["name"] for station in hidden])

        adolar4u.update_global_settings({"enabled": True})
        with self._login():
            still_hidden = self.client.get("/api/radio-stations").get_json()
        self.assertNotIn("Adolar4U", [station["name"] for station in still_hidden])

        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        with self._login():
            visible = self.client.get("/api/radio-stations").get_json()
        station = next(item for item in visible if item["name"] == "Adolar4U")
        self.assertEqual(station["engine"], "adolar4u")
        with self._login():
            needs_onboarding = self.client.get(
                f"/api/radio-stations/{station['id']}/tracks?count=3"
            )
        self.assertEqual(needs_onboarding.status_code, 428)

        with app_module.db.db() as conn:
            conn.execute("""
                INSERT INTO user_play_counts (user_id, track_id, count)
                VALUES (?, ?, 1)
            """, (self.USER_ID, self.TRACK_ID))
        with self._login():
            queue = self.client.get(
                f"/api/radio-stations/{station['id']}/tracks?count=3"
            )
        self.assertEqual(queue.status_code, 200)
        self.assertTrue(queue.headers.get("X-Shuffle-Session"))
        self.assertGreaterEqual(len(queue.get_json()), 1)

    def test_cold_start_onboarding_builds_seed_profile_and_playlist(self):
        with app_module.db.db() as conn:
            for index, (artist, genre) in enumerate((
                ("Artist Alpha", "Rock"),
                ("Artist Beta", "Jazz"),
                ("Artist Gamma", "Soul"),
                ("Artist Delta", "Pop"),
                ("Artist Epsilon", "Funk"),
            ), start=500):
                conn.execute("""
                    INSERT OR REPLACE INTO tracks
                        (id, path, title, artist, album, genre, duration)
                    VALUES (?, ?, ?, ?, 'Onboarding', ?, 240)
                """, (index, f"onboarding-{index}.mp3", f"Track {index}", artist, genre))
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})

        with self._login():
            status = self.client.get("/api/adolar4u/status").get_json()
            options = self.client.get(
                "/api/adolar4u/onboarding/options?kind=artist&q=Artist"
            ).get_json()
            completed = self.client.post("/api/adolar4u/onboarding", json={
                "artists": ["Artist Alpha", "Artist Beta", "Artist Gamma"],
                "genres": ["Rock", "Jazz", "Soul"],
            })

        self.assertTrue(status["onboarding"]["required"])
        self.assertGreaterEqual(len(options), 3)
        self.assertEqual(completed.status_code, 201)
        payload = completed.get_json()
        self.assertFalse(payload["onboarding"]["required"])
        self.assertGreaterEqual(len(payload["initial_playlist"]), 1)
        artists, genres = adolar4u.get_seed_affinities(self.USER_ID)
        self.assertEqual(artists["artist alpha"], 1.0)
        self.assertEqual(genres["rock"], 1.0)

    def test_onboarding_requires_three_catalog_values_of_each_kind(self):
        with self._login():
            too_few = self.client.post("/api/adolar4u/onboarding", json={
                "artists": ["Listener"],
                "genres": ["Electronic"],
            })
            unknown = self.client.post("/api/adolar4u/onboarding", json={
                "artists": ["Missing 1", "Missing 2", "Missing 3"],
                "genres": ["Missing 1", "Missing 2", "Missing 3"],
            })
        self.assertEqual(too_few.status_code, 400)
        self.assertEqual(unknown.status_code, 400)

    def test_metadata_mvp_prefers_strong_positive_signals(self):
        with app_module.db.db() as conn:
            for track_id, title, artist in (
                (402, "Favourite", "Loved Artist"),
                (403, "Skipped", "Skipped Artist"),
                (404, "Unknown", "Unknown Artist"),
            ):
                conn.execute("""
                    INSERT OR REPLACE INTO tracks
                        (id, path, title, artist, album, genre, duration, bpm, loved)
                    VALUES (?, ?, ?, ?, 'Signals', 'Electronic', 240, 120, ?)
                """, (
                    track_id, f"a4u-{track_id}.mp3", title, artist,
                    1 if track_id == 402 else 0,
                ))
            conn.execute("""
                INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
                VALUES (?, 402, 12, ?)
            """, (self.USER_ID, 1000))
            for index in range(4):
                conn.execute("""
                    INSERT INTO adolar4u_listening_events
                        (user_id, track_id, event_type, position_seconds,
                         duration_seconds, completion_ratio, client_event_id)
                    VALUES (?, 403, 'skipped', 8, 240, 0.033, ?)
                """, (self.USER_ID, f"early-skip-{index}"))

        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "discovery_level": 0,
        })
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=1, rng=random.Random(7),
        )
        self.assertEqual(selected[0]["id"], 402)
        self.assertIn(selected[0]["adolar4u_reason"], {
            "Favorit", "Häufig gehört", "Passender Künstler",
        })

    def test_recent_event_overrides_older_playcount_and_defers_favourite(self):
        now = 2_000_000_000.0
        base = {
            "path": "track.mp3", "album": "Album", "genre": "Electronic",
            "year": 2026, "track_no": 1, "duration": 240, "bitrate": 320,
            "size": 1, "cover_hash": None, "bpm": 120, "loved": 0,
            "library_loved": 0, "completed_count": 0, "skipped_count": 0,
            "early_skips": 0, "avg_completion": 0, "same_hour_completed": 0,
            "is_favorite": 0, "in_personal_playlist": 0, "signal_strength": 0,
        }
        recent_favourite = {
            **base, "id": 501, "title": "Recent favourite", "artist": "Known",
            "loved": 1, "user_play_count": 12,
            "last_played_at": now - 90 * 86400,
            "last_event_at": now - 60,
        }
        fresh_track = {
            **base, "id": 502, "title": "Fresh track", "artist": "New",
            "user_play_count": 0, "last_played_at": None, "last_event_at": None,
        }
        stats = {"total": 2, "artists": 2, "albums": 2, "genres": 1}

        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True, "discovery_level": 0,
        })
        with mock.patch.object(
            recommender, "_load_candidates",
            return_value=([recent_favourite, fresh_track], stats),
        ), mock.patch.object(recommender.time, "time", return_value=now):
            selected = adolar4u.recommend_tracks(
                self.USER_ID, count=1, rng=random.Random(7),
            )

        self.assertEqual(selected[0]["id"], 502)

    def test_full_recency_cooldown_applies_for_twenty_four_hours(self):
        now = 2_000_000_000.0
        row = {"last_played_at": None, "last_event_at": now - 23 * 3600}
        self.assertEqual(recommender._recency_penalty(row, now), 24.0)

        row["last_event_at"] = now - 25 * 3600
        self.assertEqual(recommender._recency_penalty(row, now), 5.0)

    def test_single_skip_is_dampened_but_repeated_skips_converge(self):
        def skip_penalties(skips):
            row = {
                "user_play_count": 0, "loved": 0, "library_loved": 0,
                "is_favorite": 0, "in_personal_playlist": 0,
                "completed_count": 0, "skipped_count": skips,
                "early_skips": skips, "same_hour_completed": 0,
                "avg_completion": 0.03, "artist": "Artist", "genre": "Genre",
                "last_played_at": None, "last_event_at": None,
            }
            recommender._score_candidate(
                row, {}, {}, 0.0, random.Random(1), 2_000_000_000.0,
            )
            return row["_adolar4u_diagnostics"]["penalties"]

        single = skip_penalties(1)
        repeated = skip_penalties(12)
        # One impatient skip must stay a mild dampener, not a ban.
        self.assertLess(single["early_skip"] + single["skip_history"], 2.0)
        # Repeated skips must still converge toward the full penalty strength.
        self.assertGreater(repeated["early_skip"], 3.9)
        self.assertGreater(
            repeated["early_skip"] + repeated["skip_history"],
            3 * (single["early_skip"] + single["skip_history"]),
        )

    def test_loved_anchor_share_is_capped_when_other_groups_exist(self):
        candidates = []
        for bucket, amount in (
            ("anchor", 70), ("similar", 30), ("familiar", 30), ("discovery", 30),
        ):
            for index in range(amount):
                candidates.append({
                    "id": len(candidates) + 1,
                    "_adolar4u_score": 1000 - len(candidates),
                    "adolar4u_bucket": bucket,
                })
        selected = recommender._choose_bucketed_candidates(
            candidates, 20, discovery=0.40,
        )
        anchors = [row for row in selected if row["adolar4u_bucket"] == "anchor"]
        self.assertEqual(len(anchors), 3)

        previous = {}
        sequential = []
        for _ in range(20):
            next_track = recommender._choose_bucketed_candidates(
                candidates, 1, discovery=0.40, previous=previous,
            )[0]
            bucket = next_track["adolar4u_bucket"]
            previous[bucket] = previous.get(bucket, 0) + 1
            sequential.append(bucket)
        self.assertEqual(sequential.count("anchor"), 3)

    def test_lastfm_loved_and_local_favorites_are_user_specific(self):
        other_user = 22
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (?, 'other-listener', 'unused', 'user', 0)
            """, (other_user,))
            conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (other_user,))
            conn.execute("DELETE FROM playlists WHERE owner_id=?", (other_user,))
        app_module.db.set_lastfm_loved(self.USER_ID, "Listener", "Signal", True)
        app_module.db.set_favorite(self.USER_ID, self.TRACK_ID, True)

        _, mine = app_module.db.search_tracks(
            query="Signal", include_loved=True, user_id=self.USER_ID,
        )
        _, theirs = app_module.db.search_tracks(
            query="Signal", include_loved=True, user_id=other_user,
        )
        self.assertTrue(next(row for row in mine if row["id"] == self.TRACK_ID)["loved"])
        self.assertFalse(next(row for row in theirs if row["id"] == self.TRACK_ID)["loved"])
        self.assertIn(self.TRACK_ID, app_module.db.get_favorite_track_ids(self.USER_ID))
        self.assertNotIn(self.TRACK_ID, app_module.db.get_favorite_track_ids(other_user))

    def test_local_and_lastfm_favorite_do_not_double_count(self):
        app_module.db.set_lastfm_loved(self.USER_ID, "Listener", "Signal", True)
        app_module.db.set_favorite(self.USER_ID, self.TRACK_ID, True)
        candidates, _ = recommender._load_candidates(self.USER_ID)
        signal = next(row for row in candidates if row["id"] == self.TRACK_ID)
        self.assertTrue(signal["loved"])
        self.assertTrue(signal["is_favorite"])
        self.assertEqual(signal["signal_strength"], 2)

    def test_favorite_auto_loves_once_but_unfavorite_keeps_lastfm_love(self):
        app_module.db.set_lastfm_account(self.USER_ID, "listener", "secret-session")
        with self._login(), mock.patch.object(app_module.lastfm, "love") as love:
            added = self.client.put(
                f"/api/favorites/{self.TRACK_ID}", json={"favorite": True},
            )
            removed = self.client.put(
                f"/api/favorites/{self.TRACK_ID}", json={"favorite": False},
            )
        self.assertEqual(added.status_code, 200)
        self.assertTrue(added.get_json()["lastfm_synced"])
        love.assert_called_once_with("secret-session", "Listener", "Signal")
        self.assertEqual(removed.status_code, 200)
        self.assertNotIn(self.TRACK_ID, app_module.db.get_favorite_track_ids(self.USER_ID))
        with app_module.db.db() as conn:
            loved = conn.execute("""
                SELECT 1 FROM lastfm_loved_tracks
                WHERE user_id=? AND artist_norm='listener' AND title_norm='signal'
            """, (self.USER_ID,)).fetchone()
        self.assertIsNotNone(loved)

    def test_lastfm_endpoints_use_the_authenticated_users_account(self):
        other_user = {**self.user, "id": 22, "username": "other-listener"}
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (22, 'other-listener', 'unused', 'user', 0)
            """)
            conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=22")
            conn.execute("DELETE FROM user_lastfm_accounts WHERE user_id=22")
        app_module.db.set_lastfm_account(self.USER_ID, "mine", "mine-key")
        app_module.db.set_lastfm_account(22, "theirs", "their-key")

        with self._login():
            mine = self.client.get("/api/lastfm/status").get_json()
        with self._login(other_user), mock.patch.object(app_module.lastfm, "love") as love:
            theirs = self.client.get("/api/lastfm/status").get_json()
            response = self.client.post("/api/lastfm/love", json={
                "artist": "Listener", "title": "Signal", "action": "love",
            })

        self.assertEqual(mine["username"], "mine")
        self.assertEqual(theirs["username"], "theirs")
        self.assertEqual(response.status_code, 200)
        love.assert_called_once_with("their-key", "Listener", "Signal")
        with app_module.db.db() as conn:
            users = conn.execute("""
                SELECT user_id FROM lastfm_loved_tracks
                WHERE artist_norm='listener' AND title_norm='signal'
            """).fetchall()
        self.assertEqual([row["user_id"] for row in users], [22])

    def test_lastfm_playback_telemetry_is_queued_without_blocking_request(self):
        app_module.db.set_lastfm_account(self.USER_ID, "listener", "session-key")
        with self._login(), mock.patch.object(
            app_module, "_submit_lastfm_call", return_value=True,
        ) as submit:
            nowplaying = self.client.post("/api/lastfm/nowplaying", json={
                "artist": "Listener", "title": "Signal", "duration": 240,
            })
            scrobble = self.client.post("/api/lastfm/scrobble", json={
                "artist": "Listener", "title": "Signal",
            })

        self.assertEqual(nowplaying.status_code, 202)
        self.assertTrue(nowplaying.get_json()["queued"])
        self.assertEqual(scrobble.status_code, 202)
        self.assertTrue(scrobble.get_json()["queued"])
        self.assertEqual(submit.call_count, 2)
        self.assertEqual(submit.call_args_list[0].args[:2], (
            "now_playing", app_module.lastfm.now_playing,
        ))
        self.assertEqual(submit.call_args_list[1].args[:2], (
            "scrobble", app_module.lastfm.scrobble,
        ))
        self.assertEqual(submit.call_args_list[1].kwargs["retries"], 1)

    def test_lastfm_telemetry_queue_saturation_is_noncritical(self):
        app_module.db.set_lastfm_account(self.USER_ID, "listener", "session-key")
        with self._login(), mock.patch.object(
            app_module, "_submit_lastfm_call", return_value=False,
        ):
            response = self.client.post("/api/lastfm/nowplaying", json={
                "artist": "Listener", "title": "Signal",
            })
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.get_json()["ok"])
        self.assertFalse(response.get_json()["queued"])

    def test_lastfm_sync_job_can_only_be_claimed_once_while_running(self):
        self.assertTrue(app_module.db.claim_lastfm_sync_job(self.USER_ID, "loved"))
        self.assertFalse(app_module.db.claim_lastfm_sync_job(self.USER_ID, "loved"))
        state = app_module.db.get_lastfm_sync_state(self.USER_ID, "loved")
        self.assertTrue(state["running"])

        app_module.db.update_lastfm_sync_state(
            self.USER_ID, "loved", running=False, result_count=12,
        )
        self.assertTrue(app_module.db.claim_lastfm_sync_job(self.USER_ID, "loved"))

    def test_legacy_global_lastfm_and_radio_favorites_migrate_to_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = os.path.join(directory, "legacy.db")
            conn = sqlite3.connect(legacy_path)
            conn.executescript("""
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO settings VALUES ('lastfm_username', 'legacy-user');
                INSERT INTO settings VALUES ('lastfm_session_key', 'legacy-key');
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
                    allow_download INTEGER NOT NULL DEFAULT 0,
                    allow_playlists INTEGER NOT NULL DEFAULT 1,
                    allow_radio_stations INTEGER NOT NULL DEFAULT 1,
                    contributes_playcount INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                INSERT INTO users (id, username, password_hash, role)
                VALUES (1, 'admin', 'unused', 'admin');
                CREATE TABLE lastfm_loved_tracks (
                    artist_norm TEXT NOT NULL, title_norm TEXT NOT NULL,
                    artist TEXT, title TEXT, loved_at INTEGER, synced_at REAL,
                    PRIMARY KEY (artist_norm, title_norm)
                );
                INSERT INTO lastfm_loved_tracks VALUES
                    ('listener', 'signal', 'Listener', 'Signal', 123, 456);
                CREATE TABLE playlists (
                    id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'smart', filters TEXT NOT NULL DEFAULT '{}',
                    sort TEXT NOT NULL DEFAULT 'artist', is_system INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                INSERT INTO playlists (id, owner_id, name, type)
                VALUES (10, 1, 'Adolar Radio Favoriten', 'static');
            """)
            conn.close()

            with mock.patch.object(app_module.db, "DB_PATH", legacy_path):
                app_module.db.init_db()
                account = app_module.db.get_lastfm_account(1)
                playlists = app_module.db.get_playlists(1)
                with app_module.db.db() as migrated:
                    loved = migrated.execute("""
                        SELECT user_id FROM lastfm_loved_tracks
                        WHERE artist_norm='listener' AND title_norm='signal'
                    """).fetchone()

            self.assertEqual(account["username"], "legacy-user")
            self.assertEqual(account["session_key"], "legacy-key")
            self.assertEqual(loved["user_id"], 1)
            favorite = next(pl for pl in playlists if pl.get("system_key") == "favorites")
            self.assertEqual(favorite["name"], "Favoriten")
            self.assertTrue(favorite["is_system"])

    def test_cold_start_still_returns_a_playable_queue(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "discovery_level": 0.2,
        })
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=3, rng=random.Random(9),
        )
        self.assertGreaterEqual(len(selected), 1)
        self.assertTrue(all(track.get("duration_fmt") for track in selected))
        self.assertTrue(all(track.get("adolar4u_reason") for track in selected))

    def test_learning_history_links_exact_decision_to_listening_outcome(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "discovery_level": 0.4,
        })
        app_module.db.set_favorite(self.USER_ID, self.TRACK_ID, True)
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=1, rng=random.Random(12),
            recommendation_session_id="test-shuffle-session",
        )
        decision_id = selected[0].get("adolar4u_decision_id")
        self.assertIsInstance(decision_id, int)

        adolar4u.record_event(self.USER_ID, self.TRACK_ID, {
            "event_type": "started",
            "duration_seconds": 200,
            "recommendation_id": decision_id,
            "client_event_id": "history-start",
        })
        adolar4u.record_event(self.USER_ID, self.TRACK_ID, {
            "event_type": "completed",
            "position_seconds": 200,
            "duration_seconds": 200,
            "recommendation_id": decision_id,
            "client_event_id": "history-complete",
        })

        with self._login():
            response = self.client.get("/api/adolar4u/history?days=7")
        self.assertEqual(response.status_code, 200)
        history = response.get_json()
        self.assertEqual(history["summary"]["recommendations"], 1)
        self.assertEqual(history["summary"]["outcomes"]["completed"], 1)
        self.assertEqual(history["summary"]["average_completion"], 1.0)
        decision = history["recommendations"][0]
        self.assertEqual(decision["id"], decision_id)
        self.assertEqual(decision["outcome"], "completed")
        self.assertEqual(decision["algorithm_version"], recommender.ALGORITHM_VERSION)
        self.assertIn("explicit_favorite", decision["diagnostics"]["bonuses"])
        self.assertIn(decision["bucket"], {"anchor", "similar", "familiar", "discovery"})

    def test_learning_export_is_complete_portable_and_user_private(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        app_module.db.set_favorite(self.USER_ID, self.TRACK_ID, True)
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=1, rng=random.Random(17),
            recommendation_session_id="export-session",
        )
        decision_id = selected[0]["adolar4u_decision_id"]
        adolar4u.record_event(self.USER_ID, selected[0]["id"], {
            "event_type": "completed",
            "position_seconds": 180,
            "duration_seconds": 180,
            "source": "adolar4u",
            "recommendation_id": decision_id,
            "client_event_id": "export-completed",
        })
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (22, 'other-export-user', 'unused', 'user', 0)
            """)
            conn.execute("""
                INSERT INTO adolar4u_recommendation_batches
                    (id, user_id, algorithm_version, requested_count,
                     candidate_count, discovery_level)
                VALUES ('private-other-batch', 22, 'private', 1, 1, 0.4)
            """)
            conn.execute("""
                INSERT INTO adolar4u_recommendations
                    (batch_id, user_id, track_id, queue_position, candidate_rank,
                     bucket, reason, score, diagnostics_json)
                VALUES ('private-other-batch', 22, ?, 1, 1, 'discovery',
                        'PRIVATE_OTHER_MARKER', 1.0, '{}')
            """, (self.TRACK_ID,))

        with self._login():
            response = self.client.get("/api/adolar4u/history/export?days=60")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertIn("adolar4u-lerndaten-", response.headers["Content-Disposition"])
        self.assertNotIn(b"PRIVATE_OTHER_MARKER", response.data)

        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), {
                "README.txt", "summary.json", "recommendations.csv",
                "listening-events.csv", "profile-batches.csv",
            })
            summary = json.loads(archive.read("summary.json"))
            recommendations = list(csv.DictReader(io.StringIO(
                archive.read("recommendations.csv").decode("utf-8-sig")
            )))
            events = list(csv.DictReader(io.StringIO(
                archive.read("listening-events.csv").decode("utf-8-sig")
            )))

        self.assertEqual(summary["row_counts"]["recommendations"], 1)
        self.assertEqual(summary["row_counts"]["listening_events"], 1)
        self.assertEqual(len(recommendations), 1)
        self.assertNotIn("PRIVATE_OTHER_MARKER", {
            row["reason"] for row in recommendations
        })
        self.assertEqual(recommendations[0]["outcome"], "completed")
        self.assertEqual(recommendations[0]["recommendation_id"], str(decision_id))
        self.assertEqual(events[0]["recommendation_id"], str(decision_id))
        self.assertNotIn("password", json.dumps(summary).lower())

    def test_paused_learning_does_not_write_recommendation_history(self):
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {
            "enabled": True,
            "learning_paused": True,
        })
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=1, rng=random.Random(8),
        )
        self.assertTrue(selected)
        self.assertNotIn("adolar4u_decision_id", selected[0])
        self.assertEqual(
            adolar4u.get_learning_history(self.USER_ID)["summary"]["recommendations"],
            0,
        )

    def test_learning_history_and_decision_links_are_user_private(self):
        with app_module.db.db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                    (id, username, password_hash, role, must_change_password)
                VALUES (22, 'other-history-user', 'unused', 'user', 0)
            """)
        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        adolar4u.update_user_settings(22, {"enabled": True})
        selected = adolar4u.recommend_tracks(
            self.USER_ID, count=1, rng=random.Random(5),
        )
        decision_id = selected[0]["adolar4u_decision_id"]

        adolar4u.record_event(22, self.TRACK_ID, {
            "event_type": "completed",
            "position_seconds": 100,
            "duration_seconds": 100,
            "recommendation_id": decision_id,
            "client_event_id": "cross-user-decision",
        })
        with app_module.db.db() as conn:
            linked = conn.execute("""
                SELECT recommendation_id FROM adolar4u_listening_events
                WHERE user_id=22 AND client_event_id='cross-user-decision'
            """).fetchone()
        self.assertIsNone(linked["recommendation_id"])

        other_user = {**self.user, "id": 22, "username": "other-history-user"}
        with self._login(other_user):
            other_history = self.client.get("/api/adolar4u/history").get_json()
        self.assertEqual(other_history["summary"]["recommendations"], 0)
        self.assertEqual(
            adolar4u.get_learning_history(self.USER_ID)["summary"]["recommendations"],
            1,
        )

    def test_existing_event_schema_upgrades_without_losing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "old-adolar4u.db")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                CREATE TABLE tracks (id INTEGER PRIMARY KEY);
                INSERT INTO users VALUES (1);
                INSERT INTO tracks VALUES (2);
                CREATE TABLE adolar4u_listening_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    position_seconds REAL NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    completion_ratio REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'unknown',
                    reason TEXT,
                    session_id TEXT,
                    client_event_id TEXT,
                    created_at REAL NOT NULL DEFAULT (unixepoch()),
                    UNIQUE(user_id, client_event_id)
                );
                INSERT INTO adolar4u_listening_events
                    (user_id, track_id, event_type, client_event_id)
                VALUES (1, 2, 'completed', 'legacy-event');
            """)
            adolar4u.init_schema(conn)
            columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(adolar4u_listening_events)"
                )
            }
            event = conn.execute("""
                SELECT client_event_id, recommendation_id
                FROM adolar4u_listening_events
            """).fetchone()
            conn.close()

        self.assertIn("recommendation_id", columns)
        self.assertEqual(event["client_event_id"], "legacy-event")
        self.assertIsNone(event["recommendation_id"])

    def test_radio_queues_include_cached_lastfm_loved_state(self):
        app_module.db.set_lastfm_loved(self.USER_ID, "Listener", "Signal", True)

        filtered = app_module.db.get_radio_filter_tracks({
            "mode": "all",
            "rules": [{"field": "artist", "op": "contains", "value": "Listener"}],
        }, count=10, user_id=self.USER_ID)
        signal = next(track for track in filtered if track["id"] == self.TRACK_ID)
        self.assertTrue(signal["loved"])

        adolar4u.update_global_settings({"enabled": True})
        adolar4u.update_user_settings(self.USER_ID, {"enabled": True})
        personalized = adolar4u.recommend_tracks(
            self.USER_ID, count=100, rng=random.Random(3),
        )
        signal = next(track for track in personalized if track["id"] == self.TRACK_ID)
        self.assertTrue(signal["loved"])


if __name__ == "__main__":
    unittest.main()
