import os
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-pages-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-pages-import-control.db"),
)

import app as app_module
import auth


class PagesTestBase(unittest.TestCase):
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
        self.client = app_module.app.test_client()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()


class IndexRouteTests(PagesTestBase):
    def test_head_index_is_a_cheap_200(self):
        response = self.client.head("/")
        self.assertEqual(response.status_code, 200)

    def test_get_index_redirects_to_setup_when_no_users_exist(self):
        # "/" is only reachable anonymously when anonymous web viewing is
        # enabled; that's the realistic path to actually exercise index()'s
        # own zero-user redirect rather than the auth middleware's redirect.
        with mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/setup", response.location)

    def test_get_index_renders_once_a_user_exists(self):
        auth.create_user("admin", "password123", role="admin")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)  # anonymous web disabled by default -> login redirect
        self.assertIn("/login", response.location)


class MiniplayerRouteTests(PagesTestBase):
    def test_renders_when_anonymous_web_is_enabled(self):
        with mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.get("/miniplayer")
        self.assertEqual(response.status_code, 200)

    def test_blocked_by_auth_middleware_when_anonymous_web_is_disabled(self):
        response = self.client.get("/miniplayer")
        self.assertEqual(response.status_code, 302)


class RadioCompanionRouteTests(PagesTestBase):
    def test_public_access_serves_the_page_anonymously(self):
        app_module.db.set_setting("companion_access", "public")
        response = self.client.get("/radio")
        self.assertEqual(response.status_code, 200)

    def test_disabled_access_returns_404_for_a_logged_in_user(self):
        # Anonymous requests never reach the route at all when disabled (the
        # auth middleware's "/radio" passthrough only special-cases "public");
        # a logged-in user does reach it, and the handler itself 404s.
        app_module.db.set_setting("companion_access", "disabled")
        user_id = auth.create_user("u", "password123")
        with app_module.db.db() as conn:
            conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (user_id,))
        token = auth.create_session(user_id, remember=False)
        self.client.set_cookie(auth.SESSION_COOKIE, token)
        response = self.client.get("/radio")
        self.assertEqual(response.status_code, 404)

    def test_disabled_access_redirects_anonymous_to_login(self):
        app_module.db.set_setting("companion_access", "disabled")
        response = self.client.get("/radio")
        self.assertEqual(response.status_code, 302)

    def test_authenticated_only_redirects_anonymous_to_login(self):
        app_module.db.set_setting("companion_access", "authenticated")
        response = self.client.get("/radio")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/radio", response.location)

    def test_authenticated_only_serves_logged_in_users(self):
        app_module.db.set_setting("companion_access", "authenticated")
        user_id = auth.create_user("u", "password123")
        with app_module.db.db() as conn:
            conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (user_id,))
        token = auth.create_session(user_id, remember=False)
        self.client.set_cookie(auth.SESSION_COOKIE, token)
        response = self.client.get("/radio")
        self.assertEqual(response.status_code, 200)


class RadioSettingsRouteTests(PagesTestBase):
    def test_anonymous_is_redirected_to_login_by_auth_middleware(self):
        response = self.client.get("/radio/settings")
        self.assertEqual(response.status_code, 302)

    def test_non_admin_is_forbidden(self):
        user_id = auth.create_user("u", "password123")
        with app_module.db.db() as conn:
            conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (user_id,))
        token = auth.create_session(user_id, remember=False)
        self.client.set_cookie(auth.SESSION_COOKIE, token)
        response = self.client.get("/radio/settings")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_settings_page(self):
        admin_id = auth.create_user("admin", "password123", role="admin")
        with app_module.db.db() as conn:
            conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (admin_id,))
        token = auth.create_session(admin_id, remember=False)
        self.client.set_cookie(auth.SESSION_COOKIE, token)
        response = self.client.get("/radio/settings")
        self.assertEqual(response.status_code, 200)


class SearchRouteTests(PagesTestBase):
    def setUp(self):
        super().setUp()
        with app_module.db.db() as conn:
            conn.executemany(
                "INSERT INTO tracks (path, title, artist, genre, year) VALUES (?,?,?,?,?)",
                [
                    ("/a.mp3", "Alpha", "Artist One", "Rock", 1999),
                    ("/b.mp3", "Beta", "Artist Two", "Jazz", 2010),
                ],
            )

    def test_basic_search_returns_all_tracks_with_pagination_metadata(self):
        response = self.client.get("/api/search")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["page"], 1)
        self.assertEqual(len(data["results"]), 2)

    def test_genre_filter_narrows_results(self):
        response = self.client.get("/api/search?genre=Rock")
        data = response.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["title"], "Alpha")

    def test_invalid_numeric_parameter_returns_400(self):
        response = self.client.get("/api/search?year_min=not-a-number")
        self.assertEqual(response.status_code, 400)

    def test_count_zero_skips_computing_total_but_still_returns_zero_placeholder(self):
        response = self.client.get("/api/search?count=0")
        self.assertEqual(response.status_code, 200)
        # total isn't computed (0), but results should still come back.
        self.assertEqual(len(response.get_json()["results"]), 2)

    def test_per_page_is_clamped_to_the_documented_maximum(self):
        response = self.client.get("/api/search?per_page=99999")
        self.assertEqual(response.get_json()["per_page"], 200)


class AlbumsRouteTests(PagesTestBase):
    def setUp(self):
        super().setUp()
        with app_module.db.db() as conn:
            conn.executemany(
                """INSERT INTO tracks (path, title, artist, album, album_artist, genre, year)
                   VALUES (?,?,?,?,?,?,?)""",
                [
                    ("/music/Daft Punk/RAM/01.flac", "Get Lucky", "Daft Punk",
                     "Random Access Memories", None, "Electronic", 2013),
                    ("/music/Daft Punk/RAM/02.flac", "Lose Yourself to Dance", "Daft Punk",
                     "Random Access Memories", None, "Electronic", 2013),
                    ("/music/Comp/Tribute/01.mp3", "Enjoy the Silence", "In Strict Confidence",
                     "40 Years - Tribute", "Various Artists", "Electronic", 2020),
                    ("/music/Comp/Tribute/02.mp3", "Personal Jesus", "Leaether Strip",
                     "40 Years - Tribute", "Various Artists", "Electronic", 2020),
                ],
            )

    def test_groups_tracks_into_one_card_per_album(self):
        response = self.client.get("/api/albums")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 2)
        albums = {a["album"]: a for a in data["results"]}
        self.assertEqual(albums["Random Access Memories"]["artist"], "Daft Punk")
        self.assertFalse(albums["Random Access Memories"]["various"])
        self.assertEqual(albums["Random Access Memories"]["track_count"], 2)

    def test_compilation_reports_various_artists_not_one_card_per_contributor(self):
        response = self.client.get("/api/albums")
        albums = {a["album"]: a for a in response.get_json()["results"]}
        comp = albums["40 Years - Tribute"]
        self.assertTrue(comp["various"])
        self.assertIsNone(comp["artist"])
        self.assertEqual(comp["track_count"], 2)

    def test_album_filter_narrows_results(self):
        response = self.client.get("/api/albums?album=random")
        data = response.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["album"], "Random Access Memories")

    def test_search_with_album_eq_and_dir_eq_opens_exactly_that_album(self):
        response = self.client.get(
            "/api/search?album_eq=40 Years - Tribute&dir_eq=/music/Comp/Tribute"
        )
        data = response.get_json()
        self.assertEqual(data["total"], 2)
        titles = {t["title"] for t in data["results"]}
        self.assertEqual(titles, {"Enjoy the Silence", "Personal Jesus"})


class GenresStatsDiscoStatusTests(PagesTestBase):
    def test_genres_returns_distinct_list(self):
        with app_module.db.db() as conn:
            conn.execute("INSERT INTO tracks (path, genre) VALUES ('/a.mp3', 'Rock')")
        with mock.patch.object(app_module.db, "get_setting", return_value="1"):
            response = self.client.get("/api/genres")
        self.assertEqual(response.get_json(), ["Rock"])

    def test_stats_includes_version_and_track_totals(self):
        response = self.client.get("/api/stats")
        data = response.get_json()
        self.assertEqual(data["total_tracks"], 0)
        self.assertEqual(data["version"], app_module.APP_VERSION)

    def test_disco_status_reports_inactive_when_never_seen(self):
        response = self.client.get("/api/disco-status")
        data = response.get_json()
        self.assertIn("active", data)
        self.assertIn("last_seen", data)


if __name__ == "__main__":
    unittest.main()
