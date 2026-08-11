import os
import sqlite3
import tempfile
import unittest
from unittest import mock

_import_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_import_temp_dir.name, "adolar-radio-import.db"))
os.environ.setdefault(
    "CONTROL_DB_PATH", os.path.join(_import_temp_dir.name, "adolar-radio-import-control.db"),
)

from adolar import db, errors


class RadioTestBase(unittest.TestCase):
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


class ValidateRadioFilterTests(unittest.TestCase):
    def test_valid_text_rule_is_kept_and_normalized(self):
        clean = db.validate_radio_filter({
            "mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "  Daft Punk  "}],
        })
        self.assertEqual(clean, {"mode": "all", "rules": [
            {"field": "artist", "op": "contains", "value": "Daft Punk"},
        ]})

    def test_empty_text_value_is_dropped(self):
        clean = db.validate_radio_filter({
            "mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "   "}],
        })
        self.assertEqual(clean["rules"], [])

    def test_invalid_operator_for_text_field_raises(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [{"field": "artist", "op": "gt", "value": "x"}],
            })

    def test_invalid_operator_for_numeric_field_raises(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [{"field": "year", "op": "contains", "value": 1999}],
            })

    def test_non_numeric_value_for_numeric_field_raises(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [{"field": "year", "op": "eq", "value": "not-a-number"}],
            })

    def test_decade_is_normalized_down_to_the_decade_start(self):
        clean = db.validate_radio_filter({
            "mode": "all", "rules": [{"field": "decade", "op": "eq", "value": 1987}],
        })
        self.assertEqual(clean["rules"][0]["value"], 1980)

    def test_added_rule_keeps_relative_age_and_unit(self):
        clean = db.validate_radio_filter({
            "mode": "all", "rules": [
                {"field": "added", "op": "before", "value": "3", "unit": "weeks"},
            ],
        })
        self.assertEqual(clean["rules"], [{
            "field": "added", "op": "before", "value": 3, "unit": "weeks",
        }])

    def test_added_rule_accepts_within_last(self):
        clean = db.validate_radio_filter({
            "mode": "all", "rules": [
                {"field": "added", "op": "within_last", "value": 2, "unit": "months"},
            ],
        })
        self.assertEqual(clean["rules"][0]["op"], "within_last")

    def test_added_rule_rejects_invalid_unit(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [
                    {"field": "added", "op": "before", "value": 3, "unit": "hours"},
                ],
            })

    def test_unknown_field_raises(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [{"field": "not-a-real-field", "op": "eq", "value": 1}],
            })

    def test_smart_editor_metadata_is_preserved_only_at_root(self):
        clean = db.validate_radio_filter({
            "mode": "all",
            "rules": [{"field": "artist", "op": "equals", "value": "Queen"}],
            "editor_version": 2,
            "editor_mode": "smart",
            "smart": {"text": "Interpret ist Queen", "interpretation": "Interpret ist exakt Queen"},
        })
        self.assertEqual(clean["editor_mode"], "smart")
        self.assertEqual(clean["smart"]["text"], "Interpret ist Queen")
        self.assertEqual(clean["rules"][0]["op"], "equals")

    def test_genre_rejects_exact_match_operator(self):
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter({
                "mode": "all", "rules": [
                    {"field": "genre", "op": "equals", "value": "Rap"},
                ],
            })

    def test_unknown_mode_falls_back_to_all(self):
        clean = db.validate_radio_filter({"mode": "bogus", "rules": []})
        self.assertEqual(clean["mode"], "all")

    def test_nested_rule_groups_are_kept_when_non_empty(self):
        clean = db.validate_radio_filter({
            "mode": "any",
            "rules": [
                {"mode": "all", "rules": [{"field": "genre", "op": "contains", "value": "Rock"}]},
            ],
        })
        self.assertEqual(clean["mode"], "any")
        self.assertEqual(len(clean["rules"]), 1)
        self.assertEqual(clean["rules"][0]["rules"][0]["field"], "genre")

    def test_empty_nested_rule_groups_are_dropped(self):
        clean = db.validate_radio_filter({
            "mode": "all",
            "rules": [{"mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "   "}]}],
        })
        self.assertEqual(clean["rules"], [])

    def test_depth_over_four_levels_raises(self):
        nested = {"field": "genre", "op": "contains", "value": "x"}
        for _ in range(6):
            nested = {"mode": "all", "rules": [nested]}
        with self.assertRaises(errors.ValidationError):
            db.validate_radio_filter(nested)

    def test_non_dict_rules_are_ignored_not_raised(self):
        clean = db.validate_radio_filter({"mode": "all", "rules": ["not-a-dict", 123, None]})
        self.assertEqual(clean["rules"], [])


class RadioFilterUsesGenreTests(unittest.TestCase):
    def test_true_for_direct_genre_rule(self):
        self.assertTrue(db._radio_filter_uses_genre(
            {"mode": "all", "rules": [{"field": "genre", "op": "contains", "value": "Rock"}]},
        ))

    def test_true_for_nested_genre_rule(self):
        self.assertTrue(db._radio_filter_uses_genre({
            "mode": "all",
            "rules": [{"mode": "any", "rules": [{"field": "genre", "op": "contains", "value": "x"}]}],
        }))

    def test_false_when_no_genre_rule_anywhere(self):
        self.assertFalse(db._radio_filter_uses_genre(
            {"mode": "all", "rules": [{"field": "artist", "op": "contains", "value": "x"}]},
        ))


class RadioFilterSqlTests(unittest.TestCase):
    def test_and_mode_joins_conditions_with_and(self):
        sql, params = db._radio_filter_sql({
            "mode": "all",
            "rules": [
                {"field": "artist", "op": "contains", "value": "Punk"},
                {"field": "year", "op": "gt", "value": 2000},
            ],
        })
        self.assertIn(" AND ", sql)
        self.assertEqual(params, ["%punk%", 2000])

    def test_or_mode_joins_conditions_with_or(self):
        sql, _ = db._radio_filter_sql({
            "mode": "any",
            "rules": [
                {"field": "artist", "op": "contains", "value": "a"},
                {"field": "artist", "op": "contains", "value": "b"},
            ],
        })
        self.assertIn(" OR ", sql)

    def test_decade_eq_produces_a_year_range(self):
        sql, params = db._radio_filter_sql({
            "mode": "all", "rules": [{"field": "decade", "op": "eq", "value": 1990}],
        })
        self.assertIn("t.year >= ? AND t.year <= ?", sql)
        self.assertEqual(params, [1990, 1999])

    def test_not_contains_wraps_the_condition_in_not(self):
        sql, _ = db._radio_filter_sql({
            "mode": "all", "rules": [{"field": "genre", "op": "not_contains", "value": "Jazz"}],
        })
        self.assertIn("NOT (", sql)

    def test_added_before_uses_an_index_timestamp_cutoff(self):
        sql, params = db._radio_filter_sql({
            "mode": "all", "rules": [
                {"field": "added", "op": "before", "value": 2, "unit": "weeks"},
            ],
        })
        self.assertEqual(sql, "t.added_at <= unixepoch('now', ?)")
        self.assertEqual(params, ["-14 days"])

    def test_added_within_last_uses_the_recent_side_of_the_cutoff(self):
        sql, params = db._radio_filter_sql({
            "mode": "all", "rules": [
                {"field": "added", "op": "within_last", "value": 2, "unit": "months"},
            ],
        })
        self.assertEqual(sql, "t.added_at >= unixepoch('now', ?)")
        self.assertEqual(params, ["-2 months"])

    def test_named_text_field_equals_is_case_insensitive_and_not_a_like(self):
        sql, params = db._radio_filter_sql({
            "mode": "all", "rules": [
                {"field": "artist", "op": "equals", "value": "Queen"},
            ],
        })
        self.assertEqual(sql, "LOWER(COALESCE(t.artist, '')) = ?")
        self.assertEqual(params, ["queen"])


class RadioStationCrudTests(RadioTestBase):
    def test_list_includes_the_seeded_system_stations(self):
        stations = db.list_radio_stations()
        names = {s["name"] for s in stations}
        self.assertIn("Adolar Radio", names)
        self.assertIn("Adolar4U", names)
        adolar_radio = next(s for s in stations if s["name"] == "Adolar Radio")
        self.assertTrue(adolar_radio["is_system"])
        self.assertEqual(adolar_radio["scope"], "global")

    def test_create_then_get_round_trips_filter_and_metadata(self):
        station_id = db.create_radio_station(
            "My Station", "desc", {"mode": "all", "rules": [
                {"field": "artist", "op": "contains", "value": "Test"},
            ]},
            user_id=5, scope="private",
        )
        station = db.get_radio_station(station_id)
        self.assertEqual(station["name"], "My Station")
        self.assertEqual(station["owner_id"], 5)
        self.assertEqual(station["scope"], "private")
        self.assertFalse(station["is_system"])
        self.assertEqual(station["filter"]["rules"][0]["field"], "artist")

    def test_global_station_has_no_owner(self):
        station_id = db.create_radio_station("Global One", "", {}, user_id=5, scope="global")
        station = db.get_radio_station(station_id)
        self.assertIsNone(station["owner_id"])

    def test_duplicate_name_in_the_same_scope_raises(self):
        db.create_radio_station("Dup", "", {}, user_id=1, scope="global")
        with self.assertRaises(sqlite3.IntegrityError):
            db.create_radio_station("Dup", "", {}, user_id=2, scope="global")

    def test_same_name_allowed_across_different_scopes_or_owners(self):
        db.create_radio_station("Same Name", "", {}, user_id=1, scope="private")
        # Different owner, same (private) scope -> should not collide.
        db.create_radio_station("Same Name", "", {}, user_id=2, scope="private")

    def test_private_station_only_listed_for_its_owner(self):
        db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        db.create_radio_station("Theirs", "", {}, user_id=2, scope="private")

        mine_visible = {s["name"] for s in db.list_radio_stations(user_id=1)}
        self.assertIn("Mine", mine_visible)
        self.assertNotIn("Theirs", mine_visible)

        all_private = {s["name"] for s in db.list_radio_stations(include_all_private=True)}
        self.assertIn("Mine", all_private)
        self.assertIn("Theirs", all_private)

    def test_owner_can_update_their_own_private_station(self):
        station_id = db.create_radio_station("Old Name", "", {}, user_id=1, scope="private")
        updated = db.update_radio_station(
            station_id, "New Name", "new desc", {}, user_id=1, is_admin=False,
        )
        self.assertTrue(updated)
        self.assertEqual(db.get_radio_station(station_id)["name"], "New Name")

    def test_non_owner_cannot_update_a_private_station(self):
        station_id = db.create_radio_station("Old Name", "", {}, user_id=1, scope="private")
        updated = db.update_radio_station(
            station_id, "Hacked", "", {}, user_id=2, is_admin=False,
        )
        self.assertFalse(updated)
        self.assertEqual(db.get_radio_station(station_id)["name"], "Old Name")

    def test_non_admin_cannot_update_a_global_station(self):
        station_id = db.create_radio_station("Global", "", {}, user_id=1, scope="global")
        updated = db.update_radio_station(
            station_id, "Hacked", "", {}, user_id=1, is_admin=False,
        )
        self.assertFalse(updated)

    def test_system_station_cannot_be_updated_or_deleted(self):
        db.list_radio_stations()  # triggers seeding
        with db.db() as conn:
            system_id = conn.execute(
                "SELECT id FROM radio_stations WHERE name='Adolar Radio'",
            ).fetchone()["id"]
        self.assertFalse(
            db.update_radio_station(system_id, "Hacked", "", {}, user_id=1, is_admin=True),
        )
        self.assertFalse(db.delete_radio_station(system_id, user_id=1, is_admin=True))

    def test_owner_can_delete_their_own_station_others_cannot(self):
        station_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")
        self.assertFalse(db.delete_radio_station(station_id, user_id=2, is_admin=False))
        self.assertTrue(db.delete_radio_station(station_id, user_id=1, is_admin=False))
        self.assertIsNone(db.get_radio_station(station_id))

    def test_can_manage_radio_station_matrix(self):
        db.list_radio_stations()  # seed system stations
        with db.db() as conn:
            system_id = conn.execute(
                "SELECT id FROM radio_stations WHERE name='Adolar Radio'",
            ).fetchone()["id"]
        private_id = db.create_radio_station("Mine", "", {}, user_id=1, scope="private")

        self.assertTrue(db.can_manage_radio_station(system_id, user_id=1, is_admin=True))
        self.assertFalse(db.can_manage_radio_station(system_id, user_id=1, is_admin=False))
        self.assertTrue(db.can_manage_radio_station(private_id, user_id=1, is_admin=False))
        self.assertFalse(db.can_manage_radio_station(private_id, user_id=2, is_admin=False))
        self.assertTrue(db.can_manage_radio_station(private_id, user_id=2, is_admin=True))
        self.assertFalse(db.can_manage_radio_station(999999, user_id=1, is_admin=True))


class RadioStationJingleTests(RadioTestBase):
    def setUp(self):
        super().setUp()
        self.station_id = db.create_radio_station("Jingle Station", "", {}, user_id=1, scope="global")

    def test_setting_a_jingle_enables_it_when_interval_is_positive(self):
        self.assertTrue(db.set_radio_station_jingle(self.station_id, "/jingles/1.mp3", 5, True))
        station = db.get_radio_station(self.station_id)
        self.assertTrue(station["has_jingle"])
        self.assertTrue(station["jingle_enabled"])

    def test_jingle_is_not_enabled_without_a_path_even_if_requested(self):
        db.set_radio_station_jingle(self.station_id, None, 5, True)
        self.assertFalse(db.get_radio_station(self.station_id)["jingle_enabled"])

    def test_jingle_is_not_enabled_with_a_zero_interval(self):
        db.set_radio_station_jingle(self.station_id, "/jingles/1.mp3", 0, True)
        self.assertFalse(db.get_radio_station(self.station_id)["jingle_enabled"])

    def test_update_jingle_settings_disables_when_path_is_missing(self):
        db.update_radio_station_jingle_settings(self.station_id, every_tracks=3, enabled=True)
        self.assertFalse(db.get_radio_station(self.station_id)["jingle_enabled"])

    def test_update_jingle_settings_enables_when_path_present(self):
        db.set_radio_station_jingle(self.station_id, "/jingles/1.mp3", 5, True)
        db.update_radio_station_jingle_settings(self.station_id, every_tracks=10, enabled=True)
        station = db.get_radio_station(self.station_id)
        self.assertTrue(station["jingle_enabled"])
        self.assertEqual(station["jingle_every_tracks"], 10)

    def test_get_jingle_path_enabled_only_hides_disabled_jingles(self):
        db.set_radio_station_jingle(self.station_id, "/jingles/1.mp3", 5, False)
        self.assertIsNone(db.get_radio_station_jingle_path(self.station_id, enabled_only=True))
        self.assertEqual(
            db.get_radio_station_jingle_path(self.station_id, enabled_only=False), "/jingles/1.mp3",
        )


if __name__ == "__main__":
    unittest.main()
