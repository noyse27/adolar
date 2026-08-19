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


def test_scan_hides_folder_action_and_loads_live_track_previews():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    repository = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryRepository.java"
    )
    assert "emptyAction.setVisibility(View.GONE)" in activity
    assert "refreshTrackPreviewDuringScan" in activity
    assert "ProgressBar scanProgress" in activity
    assert "scanExecutor" in repository
    assert "queryExecutor" in repository


def test_track_rows_are_full_width_compact_and_offer_visible_actions():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert "row.setLayoutParams(new RecyclerView.LayoutParams(" in activity
    assert "ViewGroup.LayoutParams.MATCH_PARENT, dp(73)" in activity
    assert "holder.actions.setOnClickListener" in activity
    assert "R.string.track_actions" in activity
    assert "accentLine.setBackgroundColor" in activity


def test_next_respects_system_bars_and_software_keyboard():
    manifest = read("app/src/main/AndroidManifest.xml")
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert 'android:windowSoftInputMode="adjustResize"' in manifest
    assert "WindowInsetsCompat.Type.systemBars()" in activity
    assert "WindowInsetsCompat.Type.displayCutout()" in activity
    assert "WindowInsetsCompat.Type.ime()" in activity
    assert "Math.max(bars.bottom, keyboard.bottom)" in activity
    assert "contentContainer.setPadding(" in activity
    assert "view.setPadding(" not in activity


def test_library_exposes_navigation_and_complete_mini_player_controls():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert "drawerLayout.openDrawer(Gravity.START)" in activity
    assert "toolbarBack.setVisibility(View.VISIBLE)" in activity
    assert "skipPlayback(-1)" in activity
    assert "skipPlayback(1)" in activity
    assert "adjacentTrackId" in activity
    assert "miniPlayPause" in activity


def test_local_playback_uses_a_persistent_screen_ordered_queue():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    assert "EXTRA_LOCAL_QUEUE_IDS" in activity
    assert "adapter.queueIds()" in activity
    assert "advanceLocalQueue(1)" in service
    assert 'LOCAL_PLAYBACK_PREFS = "local_playback_session"' in service
    assert "persistLocalPlayback(true)" in service
    assert "restoreLocalPlayback()" in service
    assert "ACTION_LOCAL_PLAY_NEXT" in service
    assert "ACTION_LOCAL_ADD_TO_QUEUE" in service


def test_large_local_player_has_seek_cover_source_and_love_controls():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert "buildNowPlayingPanel" in activity
    assert "playerSeek.setOnSeekBarChangeListener" in activity
    assert "getTransportControls().seekTo" in activity
    assert "loadArtwork(playerArtwork" in activity
    assert "toggleNowPlayingFavorite" in activity
    assert "Screen.NOW_PLAYING" in activity
    assert "miniPlayer.setVisibility(View.GONE)" in activity
    assert "statusView.setVisibility(View.GONE)" in activity
    assert "R.string.player_source_format" in activity


def test_local_player_shuffle_is_persistent_and_media_session_driven():
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    assert "onSetShuffleMode" in service
    assert "ACTION_SET_SHUFFLE_MODE" in service
    assert "Collections.shuffle" in service
    assert 'putBoolean("shuffle_enabled", localShuffleEnabled)' in service
    assert "original_queue_ids" in service
    assert "getTransportControls().setShuffleMode" in activity
    assert "onShuffleModeChanged" in activity
    assert "updateShuffleButton" in activity


def test_android_auto_browses_local_music_playlists_and_connected_radios():
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    main_activity = read(
        "app/src/main/java/net/polze/adolarradio/MainActivity.java"
    )
    dao = read("app/src/main/java/net/polze/adolarradio/local/LibraryDao.java")
    assert 'BROWSE_LOCAL_ROOT = "browse:local"' in service
    assert 'BROWSE_LOCAL_PLAYLISTS = "browse:local:playlists"' in service
    assert 'BROWSE_RADIOS_ROOT = "browse:radios"' in service
    assert "browserRootItems()" in service
    assert "loadPlaylistBrowserItems" in service
    assert "loadFacetBrowserItems" in service
    assert "loadBrowserLocalQueue" in service
    assert "onSearch(" in service
    assert "MAX_BROWSER_PAGE_SIZE = 200" in service
    assert "getActiveTracksPage" in dao
    assert "searchTracksPage" in dao
    assert "AdolarMediaService.BROWSE_RADIOS_ROOT" in main_activity


def test_local_search_and_facets_are_backed_by_room_queries():
    dao = read("app/src/main/java/net/polze/adolarradio/local/LibraryDao.java")
    repository = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryRepository.java"
    )
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert "List<LibraryFacet> getAlbums()" in dao
    assert "List<LibraryFacet> getArtists()" in dao
    assert "List<LibraryFacet> getGenres()" in dao
    assert "INSTR(LOWER(title), LOWER(:query))" in dao
    assert "loadTracksForFacet" in repository
    assert "new GridLayoutManager(this, 2)" in activity
    assert "showSearch()" in activity


def test_playlists_use_a_non_destructive_migration_history():
    database = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryDatabase.java"
    )
    dao = read("app/src/main/java/net/polze/adolarradio/local/LibraryDao.java")
    assert "MIGRATION_1_2" in database
    assert ".addMigrations(MIGRATION_1_2, MIGRATION_2_3)" in database
    assert "fallbackToDestructiveMigration" not in database
    assert "getStaticPlaylistTracks" in dao
    assert "getNeverPlayedTracks" in dao


def test_smart_playlists_store_a_versioned_filter_tree():
    smart_filter = read(
        "app/src/main/java/net/polze/adolarradio/local/SmartFilter.java"
    )
    repository = read(
        "app/src/main/java/net/polze/adolarradio/local/LocalLibraryRepository.java"
    )
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    assert 'saved.put("editor_version", 1)' in smart_filter
    assert 'saved.put("rules", tree)' in smart_filter
    for field in ("title", "album", "artist", "genre", "year", "decade", "playcount"):
        assert f'"{field}"' in smart_filter
    assert "SmartFilter.filter" in repository
    assert "showCreatePlaylistChoice" in activity
    assert "showAddToPlaylist" in activity


def test_local_favorites_and_playcounts_feed_system_lists():
    dao = read("app/src/main/java/net/polze/adolarradio/local/LibraryDao.java")
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    assert "void setFavorite(long trackId, boolean favorite)" in dao
    assert "void recordCompletedPlay(long trackId, long playedAt)" in dao
    assert "getMostPlayedTracks" in dao
    assert "getRecentlyPlayedTracks" in dao
    assert "getLeastPlayedTracks" in dao
    assert "showTrackActions" in activity
    assert "updateLocalPlaybackEligibility" in service
    assert "duration * 0.9d" in service


def test_local_playback_reuses_the_media_service_without_http_cache():
    service = read(
        "app/src/main/java/net/polze/adolarradio/AdolarMediaService.java"
    )
    assert 'LOCAL_TRACK_PREFIX = "local:"' in service
    assert "LocalLibraryDatabase.get(this)" in service
    assert "new DefaultDataSource.Factory(this)" in service
    assert "new Intent(this, NextActivity.class)" in service


def test_embedded_artwork_is_loaded_lazily_and_can_be_prefetched_reliably():
    gradle = read("app/build.gradle")
    activity = read("app/src/main/java/net/polze/adolarradio/NextActivity.java")
    cache = read(
        "app/src/main/java/net/polze/adolarradio/local/ArtworkCache.java"
    )
    worker = read(
        "app/src/main/java/net/polze/adolarradio/local/ArtworkPrefetchWorker.java"
    )
    assert "androidx.work:work-runtime" in gradle
    assert "getEmbeddedPicture()" in cache
    assert 'new File(this.context.getFilesDir(), "album-artwork")' in cache
    assert "MAX_ARTWORK_EDGE" in cache
    assert "ArtworkPrefetchWorker.enqueue" in activity
    assert "ExistingWorkPolicy.KEEP" in worker
    assert "loadArtwork(holder.artwork, track)" in activity
