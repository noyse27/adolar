import re
import unittest
from pathlib import Path


class SettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        cls.html = (project_root / "templates" / "index.html").read_text(encoding="utf-8")
        cls.radio_html = (project_root / "templates" / "radio.html").read_text(encoding="utf-8")
        cls.javascript = (project_root / "static" / "js" / "app.js").read_text(encoding="utf-8")

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

    def test_admin_can_open_manual_lyrics_search_without_existing_lyrics(self):
        self.assertIn('const adminFallback = _me?.role === "admin";', self.javascript)
        self.assertIn('button.classList.toggle("lyrics-missing", missing);', self.javascript)
        self.assertIn('resetLyricsSearchParams(track);', self.javascript)
        self.assertIn('resetLyricsSearchParams();', self.javascript)
        for field in ("title", "artist", "album"):
            self.assertIn(f'id="lyrics-search-{field}"', self.html)

    def test_companion_crossfade_primes_webview_media_and_survives_hidden_window(self):
        crossfade = self.radio_html.split("function startCrossfade()", 1)[1]
        crossfade = crossfade.split("// ── Audio events", 1)[0]
        self.assertIn("const playResult = inactive.play();", crossfade)
        self.assertIn("playResult.then(beginFade).catch(abortFade);", crossfade)
        self.assertIn("radio.cfTimer = setTimeout(tick, 50);", crossfade)
        self.assertNotIn("inactive.readyState", crossfade)
        self.assertNotIn("document.hidden", crossfade)

    def test_main_player_crossfade_primes_media_before_fading(self):
        normal_crossfade = self.javascript.split("function startNormalCrossfade()", 1)[1]
        normal_crossfade = normal_crossfade.split("function startCrossfade()", 1)[0]
        radio_crossfade = self.javascript.split("function startCrossfade()", 1)[1]
        radio_crossfade = radio_crossfade.split("// ── Player events", 1)[0]
        self.assertIn("const incoming = getInactiveAudio();", normal_crossfade)
        self.assertIn("const playResult = incoming.play();", normal_crossfade)
        self.assertIn("playResult.then(() =>", normal_crossfade)
        self.assertIn("finishAudioHandoff(incoming, \"normal\");", normal_crossfade)
        self.assertNotIn("audio.src = nextSrc", normal_crossfade)
        self.assertIn("const playResult = incoming.play();", radio_crossfade)
        self.assertIn("playResult.then(() =>", radio_crossfade)
        self.assertIn("finishAudioHandoff(incoming, \"radio\");", radio_crossfade)
        self.assertIn("bufferedAhead(incoming)", normal_crossfade)
        self.assertIn("bufferedAhead(incoming)", radio_crossfade)

    def test_radio_refill_is_non_blocking_until_the_queue_is_empty(self):
        radio_next = self.javascript.split("async function radioNext()", 1)[1]
        radio_next = radio_next.split("function preloadNext", 1)[0]
        self.assertIn("const refill = refillRadioQueue();", radio_next)
        self.assertIn("if (!radio.queue.length) await refill;", radio_next)

    def test_both_audio_slots_receive_guarded_player_events(self):
        self.assertIn("for (const [slot, name] of [[audioA, \"A\"], [audioB, \"B\"]])", self.javascript)
        self.assertIn("if (event.currentTarget !== audio) return;", self.javascript)


if __name__ == "__main__":
    unittest.main()
