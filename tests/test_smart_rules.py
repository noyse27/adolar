import unittest

import smart_rules


class SmartRuleParserTests(unittest.TestCase):
    def test_parses_separate_or_groups_joined_by_and(self):
        parsed = smart_rules.parse_smart_rule(
            "Album enthält Bravo oder Ronny und Jahrzehnt ist 1980 oder 1990 "
            "und Genre ist hiphop oder rap"
        )
        tree = parsed["filter"]
        self.assertEqual(tree["mode"], "all")
        self.assertEqual(len(tree["rules"]), 3)
        self.assertEqual([group["mode"] for group in tree["rules"]], ["any"] * 3)
        self.assertEqual(
            [rule["value"] for rule in tree["rules"][0]["rules"]],
            ["Bravo", "Ronny"],
        )
        self.assertEqual(
            [rule["value"] for rule in tree["rules"][1]["rules"]],
            [1980, 1990],
        )
        self.assertTrue(all(
            rule["op"] == "contains" for rule in tree["rules"][2]["rules"]
        ))

    def test_genre_is_always_means_contains(self):
        parsed = smart_rules.parse_smart_rule("Genre ist Hip-Hop")
        self.assertEqual(parsed["filter"]["rules"][0]["op"], "contains")

    def test_is_means_equals_for_named_text_fields(self):
        for text, field in (
            ("Titel ist One", "title"),
            ("Album ist First", "album"),
            ("Interpret ist Alpha", "artist"),
        ):
            with self.subTest(text=text):
                rule = smart_rules.parse_smart_rule(text)["filter"]["rules"][0]
                self.assertEqual((rule["field"], rule["op"]), (field, "equals"))

    def test_quoted_or_is_kept_inside_value(self):
        rule = smart_rules.parse_smart_rule('Album ist "Rock oder Pop"')["filter"]["rules"][0]
        self.assertEqual(rule["value"], "Rock oder Pop")

    def test_quoted_field_name_is_not_treated_as_another_clause(self):
        rule = smart_rules.parse_smart_rule('Titel ist "Genre"')["filter"]["rules"][0]
        self.assertEqual(rule["value"], "Genre")

    def test_added_relative_period_is_supported(self):
        rule = smart_rules.parse_smart_rule(
            "Hinzugefügt innerhalb der letzten 2 Monate"
        )["filter"]["rules"][0]
        self.assertEqual(rule, {
            "field": "added", "op": "within_last", "value": 2, "unit": "months",
        })

    def test_added_period_rejects_long_invalid_numeric_input(self):
        with self.assertRaises(smart_rules.SmartRuleParseError):
            smart_rules.parse_smart_rule(
                "Hinzugefügt vor " + ("9" * 1900) + "x Tagen"
            )

    def test_connector_handles_long_whitespace_without_backtracking(self):
        parsed = smart_rules.parse_smart_rule(
            "Album ist Bravo" + (" " * 1900) + "und Genre ist Rock"
        )
        tree = parsed["filter"]
        self.assertEqual(tree["mode"], "all")
        self.assertEqual([rule["field"] for rule in tree["rules"]], ["album", "genre"])

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(smart_rules.SmartRuleParseError):
            smart_rules.parse_smart_rule("Stimmung ist fröhlich")


if __name__ == "__main__":
    unittest.main()
