from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "adolar-android"


def read(relative: str) -> str:
    return (ANDROID / relative).read_text(encoding="utf-8")


def test_next_has_an_independent_android_identity():
    gradle = read("app/build.gradle")
    strings = read("app/src/main/res/values/strings.xml")
    assert 'applicationId "net.polze.adolarnext"' in gradle
    assert '<string name="app_name">Adolar Next</string>' in strings


def test_next_activity_is_the_launcher_and_radio_activity_remains_internal():
    manifest = read("app/src/main/AndroidManifest.xml")
    next_block = manifest.split('android:name=".NextActivity"', 1)[1].split(
        "</activity>", 1
    )[0]
    assert "android.intent.action.MAIN" in next_block
    assert "android.intent.category.LAUNCHER" in next_block
    assert 'android:name=".MainActivity"' in manifest
    assert 'android:exported="false"' in manifest.split(
        'android:name=".MainActivity"', 1
    )[1].split("/>", 1)[0]


def test_local_library_uses_room_and_persisted_tree_access():
    gradle = read("app/build.gradle")
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    database = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryDatabase.java"
    )
    scanner = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryScanner.java"
    )
    assert "androidx.room:room-runtime" in gradle
    assert "ACTION_OPEN_DOCUMENT_TREE" in activity
    assert "takePersistableUriPermission" in activity
    assert '"adolar-next-library.db"' in database
    assert "MediaMetadataRetriever" in scanner
    assert "markUnseenMissing" in scanner


def test_local_scan_uses_android_media_index_with_saf_fallback():
    manifest = read("app/src/main/AndroidManifest.xml")
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    scanner = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryScanner.java"
    )
    assert "android.permission.READ_MEDIA_AUDIO" in manifest
    assert "REQUEST_MEDIA_PERMISSION" in activity
    assert "MediaStore.Audio.Media.getContentUri" in scanner
    assert "MediaStore.Audio.Media.RELATIVE_PATH" in scanner
    assert "buildChildDocumentsUriUsingTree" in scanner
    assert "Already handled by the MediaStore cursor" in scanner


def test_local_playback_reuses_the_media_service_without_http_cache():
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    assert 'LOCAL_TRACK_PREFIX = "local:"' in service
    assert "LocalLibraryDatabase.get(this)" in service
    assert "new DefaultDataSource.Factory(this)" in service
    assert "new Intent(this, NextActivity.class)" in service
