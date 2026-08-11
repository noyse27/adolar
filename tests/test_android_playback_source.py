import unittest
from pathlib import Path


class AndroidPlaybackSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.service = (
            root
            / "adolar-android/app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
        ).read_text(encoding="utf-8")
        cls.gradle = (root / "adolar-android/app/build.gradle").read_text(encoding="utf-8")

    def test_media3_was_upgraded_and_uses_a_disk_cache(self):
        self.assertIn('media3-exoplayer:1.9.4', self.gradle)
        self.assertIn("new SimpleCache(", self.service)
        self.assertIn("LeastRecentlyUsedCacheEvictor(AUDIO_CACHE_BYTES)", self.service)
        self.assertIn("new CacheDataSource.Factory()", self.service)
        self.assertIn("setCustomCacheKey", self.service)

    def test_android_fetches_a_local_track_queue(self):
        self.assertIn("TRACK_BATCH_SIZE = 5", self.service)
        self.assertIn('appendQueryParameter("count", String.valueOf(count))', self.service)
        self.assertIn("ArrayDeque<Track> upcomingTracks", self.service)

    def test_crossfade_uses_two_exoplayers_and_equal_power_curve(self):
        self.assertIn("private ExoPlayer preloadPlayer;", self.service)
        self.assertIn("startAndroidCrossfade()", self.service)
        self.assertIn("Math.cos(progress * Math.PI / 2)", self.service)
        self.assertIn("Math.sin(progress * Math.PI / 2)", self.service)
        self.assertIn("completePlayerPromotion();", self.service)

    def test_only_active_player_controls_audio_focus(self):
        promotion = self.service.split("private void completePlayerPromotion()", 1)[1]
        promotion = promotion.split("private void cancelCrossfade()", 1)[0]
        self.assertIn("outgoing.setAudioAttributes(audioAttributes, false);", promotion)
        self.assertIn("incoming.setAudioAttributes(audioAttributes, true);", promotion)


if __name__ == "__main__":
    unittest.main()
