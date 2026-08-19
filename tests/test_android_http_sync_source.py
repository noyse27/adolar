from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "adolar-android"
LOCAL = "app/src/main/java/net/polze/adolarradio/local"


def read(relative: str) -> str:
    return (ANDROID / relative).read_text(encoding="utf-8")


def test_gradle_adds_keystore_backed_security_crypto():
    gradle = read("app/build.gradle")
    assert "androidx.security:security-crypto:" in gradle


def test_device_token_store_uses_encrypted_shared_preferences():
    store = read(f"{LOCAL}/DeviceTokenStore.java")
    assert "EncryptedSharedPreferences" in store
    assert "MasterKey" in store
    assert "public static String get(Context context)" in store
    assert "public static void set(Context context, String token)" in store
    assert "public static void clear(Context context)" in store


def test_http_sync_batch_sender_posts_the_events_batch_endpoint():
    sender = read(f"{LOCAL}/sync/HttpSyncBatchSender.java")
    assert "implements SyncBatchSender" in sender
    assert '"/api/android/v1/events/batch"' in sender
    assert '"Authorization", "Bearer "' in sender
    assert "DeviceTokenStore.get(context)" in sender
    assert '"event_id"' in sender
    # Missing prerequisites throw rather than silently no-op, so the
    # worker's existing catch-all reschedules the whole batch uniformly.
    assert "throw new IllegalStateException" in sender
    for outcome in ("APPLIED", "DUPLICATE", "UNMATCHED", "AMBIGUOUS",
                     "PERMANENT_ERROR", "RETRYABLE_ERROR"):
        assert outcome in sender


def test_sync_outbox_worker_now_uses_the_http_sender_by_default():
    worker = read(f"{LOCAL}/sync/SyncOutboxWorker.java")
    assert "return new HttpSyncBatchSender(context);" in worker
    assert "return new FakeLocalSyncBatchSender();" not in worker


def test_fake_sender_remains_available_for_future_tests():
    fake = read(f"{LOCAL}/sync/FakeLocalSyncBatchSender.java")
    assert "implements SyncBatchSender" in fake


def test_media_service_registers_a_device_token_on_startup():
    service = read("app/src/main/java/net/polze/adolarradio/AdolarMediaService.java")
    assert "registerDeviceIfNeeded" in service
    assert '"/api/android/v1/register-device"' in service
    assert "DeviceTokenStore.set(this, token)" in service
    assert "registerDeviceIfNeeded();" in service.split("public void onCreate()", 1)[1].split(
        "private void addPlayerDiagnostics", 1)[0]
