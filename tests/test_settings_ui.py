import re
import unittest
from pathlib import Path


class SettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        cls.html = (project_root / "templates" / "index.html").read_text(encoding="utf-8")

    def test_admin_menu_and_modal_are_named_settings(self):
        self.assertIn('<i class="ti ti-settings"></i> Einstellungen', self.html)
        self.assertIn('aria-label="Einstellungen schließen"', self.html)

    def test_settings_have_the_six_expected_collapsible_sections(self):
        modal = self.html.split("<!-- ── Administration settings modal ── -->", 1)[1]
        modal = modal.split("<!-- ── Admin system monitor ── -->", 1)[0]
        titles = re.findall(
            r'<details class="settings-section"(?: open)?>\s*'
            r'<summary><span><i[^>]*></i>\s*([^<]+)</span>',
            modal,
        )
        self.assertEqual(
            titles,
            [
                "Benutzerverwaltung",
                "Rechteverwaltung",
                "API-Zugriff",
                "Adolar4U",
                "Lyrics",
                "Administrative Historie",
            ],
        )
        self.assertEqual(modal.count('<details class="settings-section" open>'), 1)

    def test_new_user_form_is_inside_user_management_section(self):
        modal = self.html.split('<details class="settings-section" open>', 1)[1]
        user_section = modal.split('<details class="settings-section">', 1)[0]
        self.assertIn('id="new-user-name"', user_section)
        self.assertIn('id="new-user-pw"', user_section)
        self.assertIn('onclick="addUser()"', user_section)


if __name__ == "__main__":
    unittest.main()
