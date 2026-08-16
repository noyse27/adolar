package net.polze.adolarradio;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.support.v4.media.MediaBrowserCompat;
import android.support.v4.media.MediaDescriptionCompat;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaSessionCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import android.util.Log;
import android.view.KeyEvent;
import android.webkit.CookieManager;

import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;
import androidx.media.MediaBrowserServiceCompat;
import androidx.media.app.NotificationCompat.MediaStyle;
import androidx.media.session.MediaButtonReceiver;
import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.database.StandaloneDatabaseProvider;
import androidx.media3.datasource.DataSource;
import androidx.media3.datasource.DefaultDataSource;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.datasource.cache.CacheDataSource;
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor;
import androidx.media3.datasource.cache.SimpleCache;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.MediaSource;
import androidx.media3.exoplayer.source.ProgressiveMediaSource;

import net.polze.adolarradio.local.LocalLibraryDatabase;
import net.polze.adolarradio.local.LibraryDao;
import net.polze.adolarradio.local.LibraryFacet;
import net.polze.adolarradio.local.LocalPlaylist;
import net.polze.adolarradio.local.LocalTrack;
import net.polze.adolarradio.local.SmartFilter;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Playback runs on ExoPlayer (Media3) rather than the platform MediaPlayer.
 * ExoPlayer owns audio focus, "becoming noisy" handling, and the wake/WiFi
 * locks needed during network streaming (see the Builder config in
 * {@link #onCreate}), and its playlist queue provides genuinely reliable
 * gapless track transitions — a hand-rolled dual-MediaPlayer approach was
 * tried first and repeatedly left playback silent after a track change.
 */
@SuppressLint("UnsafeOptInUsageError")
public class AdolarMediaService extends MediaBrowserServiceCompat {
    private static final String TAG = "AdolarMediaService";
    private static final String ROOT_ID = "adolar_root";
    static final String BROWSE_RADIOS_ROOT = "browse:radios";
    private static final String BROWSE_LOCAL_ROOT = "browse:local";
    private static final String BROWSE_LOCAL_TRACKS = "browse:local:tracks";
    private static final String BROWSE_LOCAL_FAVORITES = "browse:local:favorites";
    private static final String BROWSE_LOCAL_ALBUMS = "browse:local:albums";
    private static final String BROWSE_LOCAL_ARTISTS = "browse:local:artists";
    private static final String BROWSE_LOCAL_GENRES = "browse:local:genres";
    private static final String BROWSE_LOCAL_PLAYLISTS = "browse:local:playlists";
    private static final String BROWSE_ALBUM_PREFIX = "browse:album:";
    private static final String BROWSE_ARTIST_PREFIX = "browse:artist:";
    private static final String BROWSE_GENRE_PREFIX = "browse:genre:";
    private static final String BROWSE_PLAYLIST_PREFIX = "browse:playlist:";
    private static final String BROWSE_SEARCH_PREFIX = "browse:search:";
    private static final String STATION_PREFIX = "station:";
    private static final String LOCAL_TRACK_PREFIX = "local:";
    static final String EXTRA_LOCAL_QUEUE_IDS =
            "net.polze.adolarradio.extra.LOCAL_QUEUE_IDS";
    static final String EXTRA_LOCAL_QUEUE_INDEX =
            "net.polze.adolarradio.extra.LOCAL_QUEUE_INDEX";
    static final String EXTRA_LOCAL_QUEUE_NAME =
            "net.polze.adolarradio.extra.LOCAL_QUEUE_NAME";
    static final String ACTION_LOCAL_PLAY_NEXT =
            "net.polze.adolarradio.action.LOCAL_PLAY_NEXT";
    static final String ACTION_LOCAL_ADD_TO_QUEUE =
            "net.polze.adolarradio.action.LOCAL_ADD_TO_QUEUE";
    static final String EXTRA_LOCAL_TRACK_ID =
            "net.polze.adolarradio.extra.LOCAL_TRACK_ID";
    static final String METADATA_KEY_ADOLAR4U_REASON =
            "net.polze.adolarradio.metadata.ADOLAR4U_REASON";
    static final String METADATA_KEY_LASTFM_LOVED =
            "net.polze.adolarradio.metadata.LASTFM_LOVED";
    static final String METADATA_KEY_HAS_LYRICS =
            "net.polze.adolarradio.metadata.HAS_LYRICS";
    private static final String PLAYBACK_CHANNEL_ID = "adolar_playback";
    private static final int PLAYBACK_NOTIFICATION_ID = 1001;
    private static final int TRACK_BATCH_SIZE = 5;
    private static final long AUDIO_CACHE_BYTES = 384L * 1024L * 1024L;
    private static final long CROSSFADE_MS = 8000L;
    private static final long CROSSFADE_TICK_MS = 50L;
    private static final long PREVIOUS_TRACK_THRESHOLD_MS = 5000L;
    private static final String LOCAL_PLAYBACK_PREFS = "local_playback_session";
    private static final int DEFAULT_BROWSER_PAGE_SIZE = 100;
    private static final int MAX_BROWSER_PAGE_SIZE = 200;
    private static SimpleCache sharedAudioCache;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final String listeningSession = "android-auto-" + UUID.randomUUID();
    private final AtomicInteger eventSequence = new AtomicInteger();
    private MediaSessionCompat mediaSession;
    private ExoPlayer player;
    private ExoPlayer preloadPlayer;
    private SimpleCache audioCache;
    private AudioAttributes audioAttributes;
    private Track currentTrack;
    private Track preloadedTrack;
    private Track restartRequestedTrack;
    private final ArrayDeque<Track> upcomingTracks = new ArrayDeque<>();
    private final ArrayDeque<Track> previousTracks = new ArrayDeque<>();
    private boolean queueRequestInFlight;
    private boolean crossfadeActive;
    private Runnable crossfadeStep;
    private long bufferingStartedMs;
    private int currentStationId = 1;
    private String currentStationName = "Adolar Radio";
    private String currentStationEngine = "shuffle";
    private boolean localMode;
    private final ArrayList<Long> localQueueIds = new ArrayList<>();
    private final ArrayList<Long> localQueueOriginalIds = new ArrayList<>();
    private int localQueueIndex = -1;
    private String localQueueName = "Lokale Musik";
    private boolean localShuffleEnabled;
    private int playbackRequest;
    private boolean foregroundStarted;

    private final Runnable crossfadeMonitor = new Runnable() {
        @Override
        public void run() {
            maybeRecordLocalPlay();
            if (!crossfadeActive && player != null && player.isPlaying()
                    && preloadedTrack != null
                    && preloadPlayer.getPlaybackState() == Player.STATE_READY) {
                long duration = player.getDuration();
                long remaining = duration == C.TIME_UNSET ? Long.MAX_VALUE : duration - player.getCurrentPosition();
                if (remaining <= CROSSFADE_MS && remaining > 0) {
                    startAndroidCrossfade();
                }
            }
            mainHandler.postDelayed(this, 250);
        }
    };

    private final Runnable connectionHeartbeat = new Runnable() {
        @Override
        public void run() {
            if (AdolarPrefs.hasServerUrl(AdolarMediaService.this)) {
                boolean playing = player.isPlaying();
                long position = player.getCurrentPosition();
                new Thread(
                        () -> sendConnectionHeartbeat(playing, position),
                        "AdolarConnectionHeartbeat"
                ).start();
            }
            if (localMode) persistLocalPlayback(true);
            mainHandler.postDelayed(this, 30000);
        }
    };

    private final Player.Listener playerListener = new Player.Listener() {
        @Override
        public void onPlaybackStateChanged(int state) {
            if (state == Player.STATE_ENDED) {
                if (!crossfadeActive) {
                    rememberCurrentTrack();
                    finishCurrentTrack(true, "ended");
                    if (localMode) {
                        if (!advanceLocalQueue(1)) {
                            clearPlayers();
                            persistLocalPlayback(false);
                            updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
                        }
                    } else {
                        promotePreloadedTrack(false);
                    }
                }
            } else if (state == Player.STATE_BUFFERING) {
                bufferingStartedMs = android.os.SystemClock.elapsedRealtime();
                Log.d(TAG, "active player buffering bufferedMs=" + bufferedDuration(player));
                updatePlaybackState(PlaybackStateCompat.STATE_BUFFERING, null);
            } else if (state == Player.STATE_READY && bufferingStartedMs != 0) {
                Log.d(TAG, "active player ready rebufferMs="
                        + (android.os.SystemClock.elapsedRealtime() - bufferingStartedMs)
                        + " bufferedMs=" + bufferedDuration(player));
                bufferingStartedMs = 0;
            }
        }

        @Override
        public void onPositionDiscontinuity(
                Player.PositionInfo oldPosition,
                Player.PositionInfo newPosition,
                int reason
        ) {
            if (reason == Player.DISCONTINUITY_REASON_SEEK
                    && newPosition.positionMs <= PREVIOUS_TRACK_THRESHOLD_MS) {
                restartRequestedTrack = null;
            }
        }

        @Override
        public void onIsPlayingChanged(boolean isPlaying) {
            int state = player.getPlaybackState();
            if (isPlaying) {
                updatePlaybackState(PlaybackStateCompat.STATE_PLAYING, null);
            } else if (state != Player.STATE_ENDED && state != Player.STATE_IDLE) {
                if (crossfadeActive) cancelCrossfade();
                updatePlaybackState(PlaybackStateCompat.STATE_PAUSED, null);
            }
        }

        @Override
        public void onPlayerError(PlaybackException error) {
            Log.w(TAG, "player error", error);
            cancelCrossfade();
            finishCurrentTrack(false, "error");
            updatePlaybackState(
                    PlaybackStateCompat.STATE_ERROR, "Wiedergabe fehlgeschlagen. Nächster Titel wird geladen."
            );
            if (localMode) {
                if (!advanceLocalQueue(1)) persistLocalPlayback(false);
            } else {
                promotePreloadedTrack(false);
            }
        }
    };

    private final MediaSessionCompat.Callback mediaCallback = new MediaSessionCompat.Callback() {
        @Override
        public void onPlay() {
            if (player.getMediaItemCount() > 0) {
                player.play();
                return;
            }
            if (localMode) {
                return;
            }
            loadNextTrack();
        }

        @Override
        public void onPlayFromMediaId(String mediaId, Bundle extras) {
            if (mediaId != null && mediaId.startsWith(LOCAL_TRACK_PREFIX)) {
                loadLocalTrack(mediaId, extras);
                return;
            }
            Station station = parseStation(mediaId, extras);
            if (station == null) {
                updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Sender nicht gefunden.");
                return;
            }
            cancelCrossfade();
            clearPlayers();
            upcomingTracks.clear();
            previousTracks.clear();
            preloadedTrack = null;
            finishCurrentTrack(false, "track_change");
            if (localMode) persistLocalPlayback(false);
            currentStationId = station.id;
            currentStationName = station.name;
            currentStationEngine = station.engine;
            localMode = false;
            mediaSession.setShuffleMode(PlaybackStateCompat.SHUFFLE_MODE_NONE);
            AdolarPrefs.setStationId(AdolarMediaService.this, station.id);
            loadNextTrack();
        }

        @Override
        public void onPlayFromSearch(String query, Bundle extras) {
            String cleanQuery = query == null ? "" : query.trim();
            if (!cleanQuery.isEmpty()) {
                playFirstBrowserTrack(BROWSE_SEARCH_PREFIX + Uri.encode(cleanQuery));
                return;
            }
            if (player.getMediaItemCount() > 0) {
                player.play();
            } else if (!localMode) {
                loadNextTrack();
            }
        }

        @Override
        public void onSkipToNext() {
            cancelCrossfade();
            if (localMode) {
                finishCurrentTrack(false, "manual_next");
                if (!advanceLocalQueue(1)) {
                    clearPlayers();
                    persistLocalPlayback(false);
                    updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
                }
                return;
            }
            rememberCurrentTrack();
            finishCurrentTrack(false, "manual_next");
            if (localMode) {
                clearPlayers();
                updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
            } else {
                promotePreloadedTrack(false);
            }
        }

        @Override
        public void onSkipToPrevious() {
            long positionMs = player.getCurrentPosition();
            boolean restartSeekPending = restartRequestedTrack == currentTrack;
            if (positionMs > PREVIOUS_TRACK_THRESHOLD_MS && !restartSeekPending) {
                restartRequestedTrack = currentTrack;
                player.seekTo(0);
                return;
            }
            restartRequestedTrack = null;
            if (localMode) {
                if (localQueueIndex <= 0) {
                    player.seekTo(0);
                    persistLocalPlayback(true);
                    return;
                }
                finishCurrentTrack(false, "manual_previous");
                advanceLocalQueue(-1);
                return;
            }
            if (previousTracks.isEmpty()) {
                player.seekTo(0);
                return;
            }
            cancelCrossfade();
            Track previous = previousTracks.removeLast();
            Track interrupted = currentTrack;
            if (preloadedTrack != null) upcomingTracks.addFirst(preloadedTrack);
            if (interrupted != null) upcomingTracks.addFirst(interrupted);
            finishCurrentTrack(false, "manual_previous");
            clearPlayers();
            preloadedTrack = null;
            startTrack(previous);
        }

        @Override
        public void onPause() {
            cancelCrossfade();
            player.pause();
            if (localMode) persistLocalPlayback(true);
        }

        @Override
        public void onSeekTo(long position) {
            player.seekTo(Math.max(0L, position));
            updatePlaybackState(player.isPlaying()
                    ? PlaybackStateCompat.STATE_PLAYING
                    : PlaybackStateCompat.STATE_PAUSED, null);
            if (localMode) persistLocalPlayback(true);
        }

        @Override
        public void onSetShuffleMode(int shuffleMode) {
            setLocalShuffleEnabled(shuffleMode == PlaybackStateCompat.SHUFFLE_MODE_ALL
                    || shuffleMode == PlaybackStateCompat.SHUFFLE_MODE_GROUP);
        }

        @Override
        public void onCustomAction(String action, Bundle extras) {
            if (!localMode || extras == null) return;
            long trackId = extras.getLong(EXTRA_LOCAL_TRACK_ID, -1L);
            if (trackId < 0L) return;
            if (ACTION_LOCAL_PLAY_NEXT.equals(action)) {
                if (currentTrack != null && currentTrack.local
                        && currentTrack.localId == trackId) return;
                long currentId = currentLocalQueueId();
                int existing = localQueueIds.indexOf(trackId);
                if (existing >= 0) {
                    localQueueIds.remove(existing);
                    if (existing <= localQueueIndex) localQueueIndex--;
                }
                localQueueIds.add(Math.min(localQueueIndex + 1, localQueueIds.size()), trackId);
                if (localShuffleEnabled) {
                    moveTrackAfter(localQueueOriginalIds, trackId, currentId);
                }
                persistLocalPlayback(true);
            } else if (ACTION_LOCAL_ADD_TO_QUEUE.equals(action)) {
                localQueueIds.add(trackId);
                if (localShuffleEnabled) localQueueOriginalIds.add(trackId);
                persistLocalPlayback(true);
            }
        }

        @Override
        public void onStop() {
            playbackRequest++;
            cancelCrossfade();
            finishCurrentTrack(false, "stop");
            clearPlayers();
            upcomingTracks.clear();
            previousTracks.clear();
            preloadedTrack = null;
            if (localMode) persistLocalPlayback(false);
            updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
            stopForeground(true);
            foregroundStarted = false;
            stopSelf();
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        currentStationId = AdolarPrefs.getStationId(this);
        audioAttributes = new AudioAttributes.Builder()
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                .setUsage(C.USAGE_MEDIA)
                .build();
        audioCache = getSharedAudioCache();
        player = buildPlayer(true);
        preloadPlayer = buildPlayer(false);
        player.addListener(playerListener);
        addPlayerDiagnostics(player);
        addPlayerDiagnostics(preloadPlayer);
        createNotificationChannel();
        mediaSession = new MediaSessionCompat(this, "AdolarNext");
        mediaSession.setFlags(
                MediaSessionCompat.FLAG_HANDLES_MEDIA_BUTTONS
                        | MediaSessionCompat.FLAG_HANDLES_TRANSPORT_CONTROLS
        );
        mediaSession.setCallback(mediaCallback);
        setSessionToken(mediaSession.getSessionToken());
        mediaSession.setShuffleMode(PlaybackStateCompat.SHUFFLE_MODE_NONE);
        // STATE_NONE makes Android Auto's playback UI inaccessible. The service
        // has playable stations even before one is selected, so advertise an
        // idle but controllable session from the start.
        updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
        mainHandler.post(connectionHeartbeat);
        mainHandler.post(crossfadeMonitor);
        restoreLocalPlayback();
    }

    private void addPlayerDiagnostics(ExoPlayer observed) {
        observed.addListener(new Player.Listener() {
            @Override
            public void onPlaybackStateChanged(int state) {
                if (observed != preloadPlayer) return;
                if (state == Player.STATE_READY) {
                    Log.d(TAG, "preload ready track="
                            + (preloadedTrack == null ? "none" : preloadedTrack.id)
                            + " bufferedMs=" + bufferedDuration(observed));
                } else if (state == Player.STATE_BUFFERING) {
                    Log.d(TAG, "preload buffering track="
                            + (preloadedTrack == null ? "none" : preloadedTrack.id));
                }
            }

            @Override
            public void onPlayerError(PlaybackException error) {
                if (observed != preloadPlayer) return;
                Log.w(TAG, "preload failed", error);
                observed.stop();
                observed.clearMediaItems();
                preloadedTrack = null;
                prepareNextTrack();
            }
        });
    }

    private ExoPlayer buildPlayer(boolean handleAudioFocus) {
        return new ExoPlayer.Builder(this)
                .setAudioAttributes(audioAttributes, handleAudioFocus)
                .setHandleAudioBecomingNoisy(true)
                .setWakeMode(C.WAKE_MODE_NETWORK)
                .build();
    }

    private SimpleCache getSharedAudioCache() {
        synchronized (AdolarMediaService.class) {
            if (sharedAudioCache == null) {
                sharedAudioCache = new SimpleCache(
                        new File(getCacheDir(), "media"),
                        new LeastRecentlyUsedCacheEvictor(AUDIO_CACHE_BYTES),
                        new StandaloneDatabaseProvider(getApplicationContext())
                );
            }
            return sharedAudioCache;
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        MediaButtonReceiver.handleIntent(mediaSession, intent);
        return START_STICKY;
    }

    @Override
    public BrowserRoot onGetRoot(String clientPackageName, int clientUid, Bundle rootHints) {
        return new BrowserRoot(ROOT_ID, null);
    }

    @Override
    public void onLoadChildren(String parentId, Result<List<MediaBrowserCompat.MediaItem>> result) {
        loadBrowserChildren(parentId, result, null);
    }

    @Override
    public void onLoadChildren(
            String parentId, Result<List<MediaBrowserCompat.MediaItem>> result,
            Bundle options
    ) {
        loadBrowserChildren(parentId, result, options);
    }

    @Override
    public void onSearch(
            String query, Bundle extras,
            Result<List<MediaBrowserCompat.MediaItem>> result
    ) {
        String cleanQuery = query == null ? "" : query.trim();
        if (cleanQuery.isEmpty()) {
            result.sendResult(new ArrayList<>());
            return;
        }
        String context = BROWSE_SEARCH_PREFIX + Uri.encode(cleanQuery);
        result.detach();
        new Thread(() -> {
            List<LocalTrack> tracks = LocalLibraryDatabase.get(this)
                    .libraryDao().searchTracksPage(cleanQuery, 50, 0);
            List<MediaBrowserCompat.MediaItem> items = localTrackItems(tracks, context);
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarAutoSearch").start();
    }

    private void loadBrowserChildren(
            String parentId, Result<List<MediaBrowserCompat.MediaItem>> result,
            Bundle options
    ) {
        if (ROOT_ID.equals(parentId)) {
            result.sendResult(browserRootItems());
            return;
        }
        if (BROWSE_LOCAL_ROOT.equals(parentId)) {
            result.sendResult(localLibraryRootItems());
            return;
        }
        if (BROWSE_RADIOS_ROOT.equals(parentId)) {
            loadRadioBrowserItems(result);
            return;
        }
        if (BROWSE_LOCAL_PLAYLISTS.equals(parentId)) {
            loadPlaylistBrowserItems(result, options);
            return;
        }
        if (BROWSE_LOCAL_ALBUMS.equals(parentId)
                || BROWSE_LOCAL_ARTISTS.equals(parentId)
                || BROWSE_LOCAL_GENRES.equals(parentId)) {
            loadFacetBrowserItems(parentId, result, options);
            return;
        }
        if (isLocalTrackContext(parentId)) {
            loadLocalTrackBrowserItems(parentId, result, options);
            return;
        }
        result.sendResult(new ArrayList<>());
    }

    private List<MediaBrowserCompat.MediaItem> browserRootItems() {
        List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
        items.add(browsableItem(
                BROWSE_LOCAL_ROOT, getString(R.string.car_local_music),
                getString(R.string.car_local_music_subtitle)
        ));
        items.add(browsableItem(
                BROWSE_LOCAL_PLAYLISTS, getString(R.string.car_playlists),
                getString(R.string.car_playlists_subtitle)
        ));
        if (AdolarPrefs.hasServerUrl(this)) {
            items.add(browsableItem(
                    BROWSE_RADIOS_ROOT, getString(R.string.car_radios),
                    getString(R.string.car_radios_subtitle)
            ));
        }
        return items;
    }

    private List<MediaBrowserCompat.MediaItem> localLibraryRootItems() {
        List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
        items.add(browsableItem(
                BROWSE_LOCAL_TRACKS, getString(R.string.car_all_tracks),
                getString(R.string.car_all_tracks_subtitle)
        ));
        items.add(browsableItem(
                BROWSE_LOCAL_FAVORITES, getString(R.string.library_drawer_favorites),
                getString(R.string.car_favorites_subtitle)
        ));
        items.add(browsableItem(
                BROWSE_LOCAL_ALBUMS, getString(R.string.library_drawer_albums), null
        ));
        items.add(browsableItem(
                BROWSE_LOCAL_ARTISTS, getString(R.string.library_drawer_artists), null
        ));
        items.add(browsableItem(
                BROWSE_LOCAL_GENRES, getString(R.string.library_drawer_genres), null
        ));
        return items;
    }

    private MediaBrowserCompat.MediaItem browsableItem(
            String mediaId, String title, String subtitle
    ) {
        MediaDescriptionCompat.Builder description = new MediaDescriptionCompat.Builder()
                .setMediaId(mediaId)
                .setTitle(title);
        if (subtitle != null && !subtitle.isEmpty()) description.setSubtitle(subtitle);
        return new MediaBrowserCompat.MediaItem(
                description.build(), MediaBrowserCompat.MediaItem.FLAG_BROWSABLE
        );
    }

    private void loadRadioBrowserItems(
            Result<List<MediaBrowserCompat.MediaItem>> result
    ) {
        if (!AdolarPrefs.hasServerUrl(this)) {
            result.sendResult(new ArrayList<>());
            return;
        }
        result.detach();
        new Thread(() -> {
            List<Station> stations = fetchStations();
            List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
            for (Station station : stations) {
                Bundle extras = new Bundle();
                extras.putInt("station_id", station.id);
                extras.putString("station_name", station.name);
                extras.putString("station_engine", station.engine);
                String subtitle = "adolar4u".equals(station.engine)
                        ? getString(R.string.car_personal_station)
                        : station.description;
                MediaDescriptionCompat description = new MediaDescriptionCompat.Builder()
                        .setMediaId(STATION_PREFIX + station.id)
                        .setTitle(station.name)
                        .setSubtitle(subtitle == null || subtitle.isEmpty()
                                ? getString(R.string.app_name) : subtitle)
                        .setExtras(extras)
                        .build();
                items.add(new MediaBrowserCompat.MediaItem(
                        description, MediaBrowserCompat.MediaItem.FLAG_PLAYABLE
                ));
                if (station.id == currentStationId) {
                    currentStationName = station.name;
                    currentStationEngine = station.engine;
                }
            }
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarStationLoader").start();
    }

    private void loadPlaylistBrowserItems(
            Result<List<MediaBrowserCompat.MediaItem>> result, Bundle options
    ) {
        PageSpec page = browserPage(options);
        result.detach();
        new Thread(() -> {
            List<LocalPlaylist> playlists = LocalLibraryDatabase.get(this)
                    .libraryDao().getPlaylists();
            List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
            for (LocalPlaylist playlist : pageSlice(playlists, page)) {
                String subtitle = playlist.isSystem
                        ? getString(R.string.car_system_playlist)
                        : "smart".equals(playlist.type)
                        ? getString(R.string.playlist_smart)
                        : getString(R.string.playlist_standard);
                items.add(browsableItem(
                        BROWSE_PLAYLIST_PREFIX + playlist.id,
                        playlist.name, subtitle
                ));
            }
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarAutoPlaylists").start();
    }

    private void loadFacetBrowserItems(
            String parentId, Result<List<MediaBrowserCompat.MediaItem>> result,
            Bundle options
    ) {
        PageSpec page = browserPage(options);
        result.detach();
        new Thread(() -> {
            LibraryDao dao = LocalLibraryDatabase.get(this).libraryDao();
            List<LibraryFacet> facets;
            String prefix;
            if (BROWSE_LOCAL_ALBUMS.equals(parentId)) {
                facets = dao.getAlbums();
                prefix = BROWSE_ALBUM_PREFIX;
            } else if (BROWSE_LOCAL_ARTISTS.equals(parentId)) {
                facets = dao.getArtists();
                prefix = BROWSE_ARTIST_PREFIX;
            } else {
                facets = dao.getGenres();
                prefix = BROWSE_GENRE_PREFIX;
            }
            List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
            for (LibraryFacet facet : pageSlice(facets, page)) {
                items.add(browsableItem(
                        prefix + Uri.encode(facet.name), facet.name,
                        getString(R.string.car_track_count, facet.trackCount)
                ));
            }
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarAutoFacets").start();
    }

    private void loadLocalTrackBrowserItems(
            String context, Result<List<MediaBrowserCompat.MediaItem>> result,
            Bundle options
    ) {
        PageSpec page = browserPage(options);
        result.detach();
        new Thread(() -> {
            List<LocalTrack> tracks = loadBrowserTrackPage(context, page);
            List<MediaBrowserCompat.MediaItem> items = localTrackItems(tracks, context);
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarAutoTracks").start();
    }

    private List<MediaBrowserCompat.MediaItem> localTrackItems(
            List<LocalTrack> tracks, String context
    ) {
        List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
        String encodedContext = Uri.encode(context);
        String queueName = browserContextName(context);
        for (LocalTrack track : tracks) {
            String title = track.title == null || track.title.isEmpty()
                    ? getString(R.string.notification_unknown_track) : track.title;
            String artist = track.artist == null || track.artist.isEmpty()
                    ? getString(R.string.library_unknown_artist) : track.artist;
            Bundle extras = new Bundle();
            extras.putLong(EXTRA_LOCAL_TRACK_ID, track.id);
            extras.putString(EXTRA_LOCAL_QUEUE_NAME, queueName);
            MediaDescriptionCompat description = new MediaDescriptionCompat.Builder()
                    .setMediaId(LOCAL_TRACK_PREFIX + track.id + "|" + encodedContext)
                    .setTitle(title)
                    .setSubtitle(artist)
                    .setDescription(track.album)
                    .setExtras(extras)
                    .build();
            items.add(new MediaBrowserCompat.MediaItem(
                    description, MediaBrowserCompat.MediaItem.FLAG_PLAYABLE
            ));
        }
        return items;
    }

    private boolean isLocalTrackContext(String parentId) {
        return BROWSE_LOCAL_TRACKS.equals(parentId)
                || BROWSE_LOCAL_FAVORITES.equals(parentId)
                || parentId.startsWith(BROWSE_ALBUM_PREFIX)
                || parentId.startsWith(BROWSE_ARTIST_PREFIX)
                || parentId.startsWith(BROWSE_GENRE_PREFIX)
                || parentId.startsWith(BROWSE_PLAYLIST_PREFIX)
                || parentId.startsWith(BROWSE_SEARCH_PREFIX);
    }

    private PageSpec browserPage(Bundle options) {
        int page = options == null
                ? 0 : Math.max(0, options.getInt(MediaBrowserCompat.EXTRA_PAGE, 0));
        int requestedSize = options == null
                ? DEFAULT_BROWSER_PAGE_SIZE
                : options.getInt(MediaBrowserCompat.EXTRA_PAGE_SIZE, DEFAULT_BROWSER_PAGE_SIZE);
        if (requestedSize <= 0) requestedSize = DEFAULT_BROWSER_PAGE_SIZE;
        int size = Math.max(1, Math.min(MAX_BROWSER_PAGE_SIZE, requestedSize));
        long offset = (long) page * size;
        return new PageSpec(size, offset > Integer.MAX_VALUE ? Integer.MAX_VALUE : (int) offset);
    }

    private <T> List<T> pageSlice(List<T> values, PageSpec page) {
        if (values == null || values.isEmpty() || page.offset >= values.size()) {
            return new ArrayList<>();
        }
        int end = (int) Math.min(values.size(), (long) page.offset + page.size);
        return new ArrayList<>(values.subList(page.offset, end));
    }

    private List<LocalTrack> loadBrowserTrackPage(String context, PageSpec page) {
        LibraryDao dao = LocalLibraryDatabase.get(this).libraryDao();
        if (BROWSE_LOCAL_TRACKS.equals(context)) {
            return dao.getActiveTracksPage(page.size, page.offset);
        }
        if (BROWSE_LOCAL_FAVORITES.equals(context)) {
            return dao.getFavoriteTracksPage(page.size, page.offset);
        }
        if (context.startsWith(BROWSE_ALBUM_PREFIX)) {
            return dao.getTracksByAlbumPage(
                    Uri.decode(context.substring(BROWSE_ALBUM_PREFIX.length())),
                    page.size, page.offset
            );
        }
        if (context.startsWith(BROWSE_ARTIST_PREFIX)) {
            return dao.getTracksByArtistPage(
                    Uri.decode(context.substring(BROWSE_ARTIST_PREFIX.length())),
                    page.size, page.offset
            );
        }
        if (context.startsWith(BROWSE_GENRE_PREFIX)) {
            return dao.getTracksByGenrePage(
                    Uri.decode(context.substring(BROWSE_GENRE_PREFIX.length())),
                    page.size, page.offset
            );
        }
        if (context.startsWith(BROWSE_SEARCH_PREFIX)) {
            return dao.searchTracksPage(
                    Uri.decode(context.substring(BROWSE_SEARCH_PREFIX.length())),
                    page.size, page.offset
            );
        }
        if (context.startsWith(BROWSE_PLAYLIST_PREFIX)) {
            long playlistId = parseBrowserPlaylistId(context);
            LocalPlaylist playlist = dao.getPlaylist(playlistId);
            if (playlist == null) return new ArrayList<>();
            if (!playlist.isSystem && !"smart".equals(playlist.type)) {
                return dao.getStaticPlaylistTracksPage(
                        playlistId, page.size, page.offset
                );
            }
            return pageSlice(loadPlaylistTracks(dao, playlist), page);
        }
        return new ArrayList<>();
    }

    private List<LocalTrack> loadBrowserQueue(String context) {
        LibraryDao dao = LocalLibraryDatabase.get(this).libraryDao();
        if (BROWSE_LOCAL_TRACKS.equals(context)) return dao.getActiveTracks();
        if (BROWSE_LOCAL_FAVORITES.equals(context)) return dao.getFavoriteTracks();
        if (context.startsWith(BROWSE_ALBUM_PREFIX)) {
            return dao.getTracksByAlbum(Uri.decode(
                    context.substring(BROWSE_ALBUM_PREFIX.length())
            ));
        }
        if (context.startsWith(BROWSE_ARTIST_PREFIX)) {
            return dao.getTracksByArtist(Uri.decode(
                    context.substring(BROWSE_ARTIST_PREFIX.length())
            ));
        }
        if (context.startsWith(BROWSE_GENRE_PREFIX)) {
            return dao.getTracksByGenre(Uri.decode(
                    context.substring(BROWSE_GENRE_PREFIX.length())
            ));
        }
        if (context.startsWith(BROWSE_SEARCH_PREFIX)) {
            return dao.searchTracks(Uri.decode(
                    context.substring(BROWSE_SEARCH_PREFIX.length())
            ));
        }
        if (context.startsWith(BROWSE_PLAYLIST_PREFIX)) {
            LocalPlaylist playlist = dao.getPlaylist(parseBrowserPlaylistId(context));
            return playlist == null ? new ArrayList<>() : loadPlaylistTracks(dao, playlist);
        }
        return new ArrayList<>();
    }

    private List<LocalTrack> loadPlaylistTracks(
            LibraryDao dao, LocalPlaylist playlist
    ) {
        if (!playlist.isSystem) {
            if ("smart".equals(playlist.type)) {
                return SmartFilter.filter(
                        dao.getActiveTracks(), dao.getTrackStates(), playlist.filterJson
                );
            }
            return dao.getStaticPlaylistTracks(playlist.id);
        }
        if ("favorites".equals(playlist.systemKey)) return dao.getFavoriteTracks();
        if ("recently_added".equals(playlist.systemKey)) return dao.getRecentlyAddedTracks();
        if ("most_played".equals(playlist.systemKey)) return dao.getMostPlayedTracks();
        if ("recently_played".equals(playlist.systemKey)) return dao.getRecentlyPlayedTracks();
        if ("least_played".equals(playlist.systemKey)) return dao.getLeastPlayedTracks();
        if ("never_played".equals(playlist.systemKey)) return dao.getNeverPlayedTracks();
        return new ArrayList<>();
    }

    private long parseBrowserPlaylistId(String context) {
        try {
            return Long.parseLong(context.substring(BROWSE_PLAYLIST_PREFIX.length()));
        } catch (RuntimeException ignored) {
            return -1L;
        }
    }

    private String browserContextName(String context) {
        if (BROWSE_LOCAL_TRACKS.equals(context)) return getString(R.string.library_tracks);
        if (BROWSE_LOCAL_FAVORITES.equals(context)) {
            return getString(R.string.library_drawer_favorites);
        }
        if (context.startsWith(BROWSE_ALBUM_PREFIX)) {
            return Uri.decode(context.substring(BROWSE_ALBUM_PREFIX.length()));
        }
        if (context.startsWith(BROWSE_ARTIST_PREFIX)) {
            return Uri.decode(context.substring(BROWSE_ARTIST_PREFIX.length()));
        }
        if (context.startsWith(BROWSE_GENRE_PREFIX)) {
            return Uri.decode(context.substring(BROWSE_GENRE_PREFIX.length()));
        }
        if (context.startsWith(BROWSE_SEARCH_PREFIX)) {
            return getString(
                    R.string.car_search_results,
                    Uri.decode(context.substring(BROWSE_SEARCH_PREFIX.length()))
            );
        }
        if (context.startsWith(BROWSE_PLAYLIST_PREFIX)) {
            LocalPlaylist playlist = LocalLibraryDatabase.get(this).libraryDao()
                    .getPlaylist(parseBrowserPlaylistId(context));
            if (playlist != null && playlist.name != null && !playlist.name.isEmpty()) {
                return playlist.name;
            }
        }
        return getString(R.string.local_source);
    }

    private Station parseStation(String mediaId, Bundle extras) {
        if (mediaId == null || !mediaId.startsWith(STATION_PREFIX)) {
            return null;
        }
        try {
            Station station = new Station();
            station.id = Integer.parseInt(mediaId.substring(STATION_PREFIX.length()));
            station.name = extras == null ? "Adolar Radio" : extras.getString("station_name", "Adolar Radio");
            station.engine = extras == null ? "shuffle" : extras.getString("station_engine", "shuffle");
            return station;
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    private void loadLocalTrack(String mediaId, Bundle extras) {
        BrowserLocalRequest request = parseBrowserLocalRequest(mediaId);
        if (request == null) {
            updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Lokaler Titel nicht gefunden.");
            return;
        }
        if (request.context != null && !request.context.isEmpty()) {
            loadBrowserLocalQueue(request.trackId, request.context);
            return;
        }
        startConfiguredLocalTrack(request.trackId, extras);
    }

    private BrowserLocalRequest parseBrowserLocalRequest(String mediaId) {
        if (mediaId == null || !mediaId.startsWith(LOCAL_TRACK_PREFIX)) return null;
        String payload = mediaId.substring(LOCAL_TRACK_PREFIX.length());
        int separator = payload.indexOf('|');
        String id = separator < 0 ? payload : payload.substring(0, separator);
        try {
            BrowserLocalRequest request = new BrowserLocalRequest();
            request.trackId = Long.parseLong(id);
            request.context = separator < 0
                    ? null : Uri.decode(payload.substring(separator + 1));
            return request;
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private void playFirstBrowserTrack(String context) {
        loadBrowserLocalQueue(-1L, context);
    }

    private void loadBrowserLocalQueue(long requestedTrackId, String context) {
        final int request = ++playbackRequest;
        updatePlaybackState(PlaybackStateCompat.STATE_BUFFERING, null);
        new Thread(() -> {
            List<LocalTrack> tracks = loadBrowserQueue(context);
            if (tracks == null || tracks.isEmpty()) {
                mainHandler.post(() -> {
                    if (request != playbackRequest) return;
                    updatePlaybackState(
                            PlaybackStateCompat.STATE_ERROR,
                            getString(R.string.car_no_local_tracks)
                    );
                });
                return;
            }
            long resolvedTrackId = requestedTrackId < 0L
                    ? tracks.get(0).id : requestedTrackId;
            long[] queueIds = new long[tracks.size()];
            int resolvedIndex = -1;
            for (int index = 0; index < tracks.size(); index++) {
                queueIds[index] = tracks.get(index).id;
                if (queueIds[index] == resolvedTrackId && resolvedIndex < 0) {
                    resolvedIndex = index;
                }
            }
            if (resolvedIndex < 0) {
                resolvedTrackId = tracks.get(0).id;
                resolvedIndex = 0;
            }
            String queueName = browserContextName(context);
            long selectedTrackId = resolvedTrackId;
            int selectedIndex = resolvedIndex;
            mainHandler.post(() -> {
                if (request != playbackRequest) return;
                Bundle queueExtras = new Bundle();
                queueExtras.putLongArray(EXTRA_LOCAL_QUEUE_IDS, queueIds);
                queueExtras.putInt(EXTRA_LOCAL_QUEUE_INDEX, selectedIndex);
                queueExtras.putString(EXTRA_LOCAL_QUEUE_NAME, queueName);
                startConfiguredLocalTrack(selectedTrackId, queueExtras);
            });
        }, "AdolarAutoQueue").start();
    }

    private void startConfiguredLocalTrack(long localTrackId, Bundle extras) {
        configureLocalQueue(localTrackId, extras);
        localMode = true;
        publishLocalShuffleMode();
        currentStationName = localQueueName;
        currentStationEngine = "local";
        loadLocalTrackById(localTrackId, true, true, 0L);
    }

    private void configureLocalQueue(long requestedTrackId, Bundle extras) {
        long[] requestedQueue = extras == null
                ? null : extras.getLongArray(EXTRA_LOCAL_QUEUE_IDS);
        if (requestedQueue != null && requestedQueue.length > 0) {
            localQueueIds.clear();
            int requestedIndex = extras.getInt(EXTRA_LOCAL_QUEUE_INDEX, -1);
            for (long trackId : requestedQueue) localQueueIds.add(trackId);
            localQueueIndex = requestedIndex >= 0 && requestedIndex < localQueueIds.size()
                    && localQueueIds.get(requestedIndex) == requestedTrackId
                    ? requestedIndex : localQueueIds.indexOf(requestedTrackId);
            localQueueName = extras.getString(EXTRA_LOCAL_QUEUE_NAME, "Lokale Musik");
        } else {
            localQueueIds.clear();
            localQueueIds.add(requestedTrackId);
            localQueueIndex = 0;
            localQueueName = "Lokale Musik";
        }
        if (localQueueIndex < 0) {
            localQueueIds.add(requestedTrackId);
            localQueueIndex = localQueueIds.size() - 1;
        }
        prepareLocalShuffleQueue();
    }

    private boolean advanceLocalQueue(int direction) {
        int nextIndex = localQueueIndex + direction;
        if (nextIndex < 0 || nextIndex >= localQueueIds.size()) return false;
        localQueueIndex = nextIndex;
        loadLocalTrackById(localQueueIds.get(nextIndex), false, true, 0L);
        return true;
    }

    private void setLocalShuffleEnabled(boolean enabled) {
        if (!localMode) {
            mediaSession.setShuffleMode(PlaybackStateCompat.SHUFFLE_MODE_NONE);
            return;
        }
        if (localShuffleEnabled == enabled) {
            publishLocalShuffleMode();
            return;
        }
        long currentId = currentLocalQueueId();
        if (enabled) {
            localShuffleEnabled = true;
            prepareLocalShuffleQueue();
        } else {
            localShuffleEnabled = false;
            if (!localQueueOriginalIds.isEmpty()) {
                localQueueIds.clear();
                localQueueIds.addAll(localQueueOriginalIds);
                localQueueIndex = localQueueIds.indexOf(currentId);
                if (localQueueIndex < 0 && !localQueueIds.isEmpty()) localQueueIndex = 0;
            }
            localQueueOriginalIds.clear();
        }
        publishLocalShuffleMode();
        persistLocalPlayback(true);
    }

    private void prepareLocalShuffleQueue() {
        localQueueOriginalIds.clear();
        if (!localShuffleEnabled) return;
        localQueueOriginalIds.addAll(localQueueIds);
        int firstUnplayed = Math.max(0, localQueueIndex + 1);
        if (firstUnplayed < localQueueIds.size() - 1) {
            Collections.shuffle(localQueueIds.subList(firstUnplayed, localQueueIds.size()));
        }
    }

    private void publishLocalShuffleMode() {
        mediaSession.setShuffleMode(localShuffleEnabled
                ? PlaybackStateCompat.SHUFFLE_MODE_ALL
                : PlaybackStateCompat.SHUFFLE_MODE_NONE);
    }

    private long currentLocalQueueId() {
        return localQueueIndex >= 0 && localQueueIndex < localQueueIds.size()
                ? localQueueIds.get(localQueueIndex) : -1L;
    }

    private void moveTrackAfter(List<Long> queue, long trackId, long currentId) {
        int existing = queue.indexOf(trackId);
        if (existing >= 0) queue.remove(existing);
        int currentIndex = queue.indexOf(currentId);
        queue.add(Math.min(currentIndex < 0 ? queue.size() : currentIndex + 1, queue.size()), trackId);
    }

    private void loadLocalTrackById(
            long localTrackId, boolean finishPrevious, boolean playWhenReady,
            long startPositionMs
    ) {
        final int request = ++playbackRequest;
        updatePlaybackState(
                playWhenReady ? PlaybackStateCompat.STATE_BUFFERING
                        : PlaybackStateCompat.STATE_PAUSED,
                null
        );
        new Thread(() -> {
            LocalTrack local = LocalLibraryDatabase.get(this)
                    .libraryDao().getTrack(localTrackId);
            mainHandler.post(() -> {
                if (request != playbackRequest) return;
                if (local == null || local.missing) {
                    if (!advanceLocalQueue(1)) {
                        localMode = false;
                        persistLocalPlayback(false);
                        updatePlaybackState(
                                PlaybackStateCompat.STATE_ERROR,
                                "Lokaler Titel nicht gefunden."
                        );
                    }
                    return;
                }
                cancelCrossfade();
                if (finishPrevious) finishCurrentTrack(false, "track_change");
                clearPlayers();
                upcomingTracks.clear();
                previousTracks.clear();
                preloadedTrack = null;
                localMode = true;
                currentStationName = localQueueName;
                currentStationEngine = "local";

                Track track = new Track();
                track.local = true;
                track.localId = local.id;
                track.localDocumentUri = local.documentUri;
                track.title = local.title == null || local.title.isEmpty()
                        ? "Unbekannter Titel" : local.title;
                track.artist = local.artist == null || local.artist.isEmpty()
                        ? "Unbekannter Interpret" : local.artist;
                track.album = local.album == null ? "" : local.album;
                track.year = local.year == null ? 0 : local.year;
                track.durationMs = local.durationSeconds * 1000L;
                startTrack(track, playWhenReady, startPositionMs);
                persistLocalPlayback(true);
            });
        }, "AdolarLocalTrackLoader").start();
    }

    private List<Station> fetchStations() {
        List<Station> stations = new ArrayList<>();
        HttpURLConnection connection = null;
        try {
            connection = openConnection(AdolarPrefs.apiUrl(this) + "/api/radio-stations", "GET");
            if (!isSuccessful(connection)) {
                return stations;
            }
            JSONArray array = new JSONArray(readAll(connection.getInputStream()));
            for (int index = 0; index < array.length(); index++) {
                JSONObject item = array.getJSONObject(index);
                Station station = new Station();
                station.id = item.getInt("id");
                station.name = item.optString("name", "Adolar Radio");
                station.description = item.optString("description", "");
                station.engine = item.optString("engine", "shuffle");
                stations.add(station);
            }
        } catch (Exception ignored) {
            // Android Auto shows an empty list while the server is unavailable.
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
        return stations;
    }

    private void loadNextTrack() {
        if (!AdolarPrefs.hasServerUrl(this)) {
            updatePlaybackState(PlaybackStateCompat.STATE_ERROR, getString(R.string.car_no_server));
            return;
        }
        if (!upcomingTracks.isEmpty()) {
            startTrack(upcomingTracks.removeFirst());
            return;
        }
        final int request = ++playbackRequest;
        queueRequestInFlight = true;
        updatePlaybackState(PlaybackStateCompat.STATE_BUFFERING, null);
        new Thread(() -> {
            long started = android.os.SystemClock.elapsedRealtime();
            List<Track> tracks = fetchStationTracks(currentStationId, TRACK_BATCH_SIZE);
            Log.d(TAG, "track batch loaded count=" + tracks.size() + " durationMs="
                    + (android.os.SystemClock.elapsedRealtime() - started));
            mainHandler.post(() -> {
                queueRequestInFlight = false;
                if (request != playbackRequest) {
                    return;
                }
                if (tracks.isEmpty()) {
                    updatePlaybackState(
                            PlaybackStateCompat.STATE_ERROR,
                            "Sender nicht verfügbar. Für Adolar4U bitte in der Handy-App anmelden."
                    );
                } else {
                    upcomingTracks.addAll(tracks);
                    startTrack(upcomingTracks.removeFirst());
                }
            });
        }, "AdolarTrackLoader").start();
    }

    private List<Track> fetchStationTracks(int stationId, int count) {
        List<Track> result = new ArrayList<>();
        HttpURLConnection connection = null;
        try {
            Uri.Builder urlBuilder = Uri.parse(
                    AdolarPrefs.apiUrl(this) + "/api/radio-stations/" + stationId + "/tracks"
            ).buildUpon().appendQueryParameter("count", String.valueOf(count));
            String shuffleSession = AdolarPrefs.getShuffleSession(this, stationId);
            if (!shuffleSession.isEmpty()) {
                urlBuilder.appendQueryParameter("shuffle_session", shuffleSession);
            }
            connection = openConnection(urlBuilder.build().toString(), "GET");
            if (!isSuccessful(connection)) {
                return result;
            }
            String nextSession = connection.getHeaderField("X-Shuffle-Session");
            if (nextSession != null && !nextSession.isEmpty()) {
                AdolarPrefs.setShuffleSession(this, stationId, nextSession);
            }
            JSONArray tracks = new JSONArray(readAll(connection.getInputStream()));
            for (int index = 0; index < tracks.length(); index++) {
                JSONObject item = tracks.getJSONObject(index);
                Track track = new Track();
                track.id = item.getInt("id");
                track.title = item.optString("title", "Unbekannter Titel");
                track.artist = item.optString("artist", "Unbekannter Artist");
                track.album = item.optString("album", "");
                track.year = item.optInt("year", 0);
                track.reason = item.optString("adolar4u_reason", "");
                track.loved = item.optBoolean("loved", false);
                track.durationMs = item.optLong("duration", 0) * 1000L;
                track.coverHash = item.optString("cover_hash", "");
                track.hasCover = item.optBoolean("has_cover", false);
                track.hasLyrics = item.optBoolean("has_lyrics", false);
                track.streamVersion = item.optString("stream_version", "");
                result.add(track);
            }
            return result;
        } catch (Exception exception) {
            Log.w(TAG, "track batch request failed", exception);
            return result;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void startTrack(Track track) {
        startTrack(track, true, 0L);
    }

    private void startTrack(Track track, boolean playWhenReady, long startPositionMs) {
        restartRequestedTrack = null;
        currentTrack = track;
        mediaSession.setActive(true);
        updateMetadata(track);
        if (!track.local) {
            requestLyricsIfMissing(track);
        }
        // Marks the service as "started" so it survives the phone UI unbinding
        // (e.g. screen off triggers MainActivity.onStop -> mediaBrowser.disconnect()).
        // Without this the service is bound-only and Android destroys it, and the
        // player with it, the moment the last bound client goes away.
        ContextCompat.startForegroundService(this, new Intent(this, AdolarMediaService.class));
        startForeground(PLAYBACK_NOTIFICATION_ID, buildNotification());
        foregroundStarted = true;
        player.setMediaSource(buildMediaSource(track));
        player.prepare();
        if (startPositionMs > 0L) player.seekTo(startPositionMs);
        player.setPlayWhenReady(playWhenReady);
        if (!playWhenReady) updatePlaybackState(PlaybackStateCompat.STATE_PAUSED, null);
        if (!track.local) {
            sendListeningEvent(track, "started", null, 0, track.durationMs);
            prepareNextTrack();
        }
    }

    private MediaSource buildMediaSource(Track track) {
        if (track.local) {
            MediaItem mediaItem = new MediaItem.Builder()
                    .setUri(Uri.parse(track.localDocumentUri))
                    .setMediaId(LOCAL_TRACK_PREFIX + track.localId)
                    .build();
            return new ProgressiveMediaSource.Factory(new DefaultDataSource.Factory(this))
                    .createMediaSource(mediaItem);
        }
        Map<String, String> headers = new HashMap<>();
        String cookie = sessionCookie();
        if (!cookie.isEmpty()) {
            headers.put("Cookie", cookie);
        }
        DefaultHttpDataSource.Factory upstreamFactory = new DefaultHttpDataSource.Factory()
                .setDefaultRequestProperties(headers);
        CacheDataSource.Factory dataSourceFactory = new CacheDataSource.Factory()
                .setCache(audioCache)
                .setUpstreamDataSourceFactory(upstreamFactory)
                .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR);
        String versionQuery = track.streamVersion.isEmpty()
                ? "" : "?v=" + Uri.encode(track.streamVersion);
        MediaItem mediaItem = new MediaItem.Builder()
                .setUri(Uri.parse(AdolarPrefs.apiUrl(this) + "/api/stream/" + track.id + versionQuery))
                .setMediaId(String.valueOf(track.id))
                .setCustomCacheKey("track-" + track.id + "-" + track.streamVersion)
                .build();
        return new ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(mediaItem);
    }

    private void requestMoreTracks() {
        if (localMode || queueRequestInFlight || !AdolarPrefs.hasServerUrl(this)) return;
        queueRequestInFlight = true;
        final int owningRequest = playbackRequest;
        new Thread(() -> {
            long started = android.os.SystemClock.elapsedRealtime();
            List<Track> tracks = fetchStationTracks(currentStationId, TRACK_BATCH_SIZE);
            mainHandler.post(() -> {
                queueRequestInFlight = false;
                if (owningRequest != playbackRequest) return;
                upcomingTracks.addAll(tracks);
                Log.d(TAG, "queue refill count=" + tracks.size() + " durationMs="
                        + (android.os.SystemClock.elapsedRealtime() - started));
                prepareNextTrack();
            });
        }, "AdolarTrackQueueLoader").start();
    }

    private void prepareNextTrack() {
        if (localMode || preloadedTrack != null) return;
        if (upcomingTracks.isEmpty()) {
            requestMoreTracks();
            return;
        }
        preloadedTrack = upcomingTracks.removeFirst();
        preloadPlayer.setVolume(0f);
        preloadPlayer.setMediaSource(buildMediaSource(preloadedTrack));
        preloadPlayer.prepare();
        preloadPlayer.setPlayWhenReady(false);
        Log.d(TAG, "preload source added track=" + preloadedTrack.id);
        if (upcomingTracks.size() <= 1) requestMoreTracks();
    }

    private void startAndroidCrossfade() {
        if (crossfadeActive || preloadedTrack == null
                || preloadPlayer.getPlaybackState() != Player.STATE_READY) return;
        crossfadeActive = true;
        final ExoPlayer outgoing = player;
        final ExoPlayer incoming = preloadPlayer;
        final long started = android.os.SystemClock.elapsedRealtime();
        incoming.setVolume(0f);
        incoming.play();
        Log.d(TAG, "crossfade start track=" + preloadedTrack.id
                + " bufferedMs=" + bufferedDuration(incoming));
        crossfadeStep = new Runnable() {
            @Override
            public void run() {
                if (!crossfadeActive || outgoing != player || incoming != preloadPlayer) return;
                float progress = Math.min(1f,
                        (android.os.SystemClock.elapsedRealtime() - started) / (float) CROSSFADE_MS);
                outgoing.setVolume((float) Math.cos(progress * Math.PI / 2));
                incoming.setVolume((float) Math.sin(progress * Math.PI / 2));
                if (progress < 1f) {
                    mainHandler.postDelayed(this, CROSSFADE_TICK_MS);
                    return;
                }
                rememberCurrentTrack();
                finishCurrentTrack(true, "ended");
                completePlayerPromotion();
                Log.d(TAG, "crossfade end durationMs="
                        + (android.os.SystemClock.elapsedRealtime() - started));
            }
        };
        mainHandler.post(crossfadeStep);
    }

    private void promotePreloadedTrack(boolean alreadyPlaying) {
        if (preloadedTrack == null) {
            clearPlayers();
            loadNextTrack();
            return;
        }
        if (!alreadyPlaying) {
            preloadPlayer.setVolume(1f);
            preloadPlayer.play();
        }
        completePlayerPromotion();
    }

    private void completePlayerPromotion() {
        Track promoted = preloadedTrack;
        ExoPlayer outgoing = player;
        ExoPlayer incoming = preloadPlayer;
        outgoing.removeListener(playerListener);
        outgoing.stop();
        outgoing.clearMediaItems();
        outgoing.setVolume(0f);
        outgoing.setAudioAttributes(audioAttributes, false);
        incoming.setAudioAttributes(audioAttributes, true);
        player = incoming;
        preloadPlayer = outgoing;
        player.addListener(playerListener);
        player.setVolume(1f);
        preloadedTrack = null;
        crossfadeActive = false;
        restartRequestedTrack = null;
        currentTrack = promoted;
        mediaSession.setActive(true);
        updateMetadata(promoted);
        requestLyricsIfMissing(promoted);
        sendListeningEvent(promoted, "started", null, 0, promoted.durationMs);
        updatePlaybackState(PlaybackStateCompat.STATE_PLAYING, null);
        prepareNextTrack();
    }

    private void cancelCrossfade() {
        if (crossfadeStep != null) mainHandler.removeCallbacks(crossfadeStep);
        crossfadeStep = null;
        crossfadeActive = false;
        if (player != null) player.setVolume(1f);
        if (preloadPlayer != null) {
            preloadPlayer.pause();
            preloadPlayer.seekTo(0);
            preloadPlayer.setVolume(0f);
        }
    }

    private void clearPlayers() {
        restartRequestedTrack = null;
        if (player != null) {
            player.stop();
            player.clearMediaItems();
        }
        if (preloadPlayer != null) {
            preloadPlayer.stop();
            preloadPlayer.clearMediaItems();
        }
    }

    private long bufferedDuration(ExoPlayer target) {
        return Math.max(0L, target.getBufferedPosition() - target.getCurrentPosition());
    }

    private void retryCurrentRequestAfterDelay(int failedRequest) {
        mainHandler.postDelayed(() -> {
            if (failedRequest == playbackRequest && mediaSession != null) {
                loadNextTrack();
            }
        }, 1500);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                PLAYBACK_CHANNEL_ID,
                getString(R.string.playback_channel_name),
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription(getString(R.string.playback_channel_description));
        channel.setShowBadge(false);
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Intent contentIntent = new Intent(this, NextActivity.class);
        int pendingFlags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent contentPendingIntent = PendingIntent.getActivity(this, 0, contentIntent, pendingFlags);
        MediaStyle mediaStyle = new MediaStyle()
                .setMediaSession(mediaSession.getSessionToken())
                .setShowActionsInCompactView(0, 1, 2);
        String title = currentTrack == null
                ? getString(R.string.notification_unknown_track)
                : currentTrack.title;
        String artist = currentTrack == null ? currentStationName : currentTrack.artist;
        boolean playing = player.isPlaying();
        return new NotificationCompat.Builder(this, PLAYBACK_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_car_attribution)
                .setContentTitle(title)
                .setContentText(artist)
                .setSubText(currentStationName)
                .setContentIntent(contentPendingIntent)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setOnlyAlertOnce(true)
                .setOngoing(playing)
                .addAction(mediaAction(KeyEvent.KEYCODE_MEDIA_PREVIOUS, android.R.drawable.ic_media_previous, "Zurück"))
                .addAction(mediaAction(
                        playing ? KeyEvent.KEYCODE_MEDIA_PAUSE : KeyEvent.KEYCODE_MEDIA_PLAY,
                        playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                        playing ? "Pause" : "Wiedergabe"
                ))
                .addAction(mediaAction(KeyEvent.KEYCODE_MEDIA_NEXT, android.R.drawable.ic_media_next, "Weiter"))
                .setStyle(mediaStyle)
                .build();
    }

    private NotificationCompat.Action mediaAction(int keyCode, int icon, String title) {
        Intent intent = new Intent(Intent.ACTION_MEDIA_BUTTON, null, this, AdolarMediaService.class);
        intent.putExtra(Intent.EXTRA_KEY_EVENT, new KeyEvent(KeyEvent.ACTION_DOWN, keyCode));
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent pendingIntent = PendingIntent.getService(this, keyCode, intent, flags);
        return new NotificationCompat.Action(icon, title, pendingIntent);
    }

    private void finishCurrentTrack(boolean completed, String reason) {
        Track track = currentTrack;
        if (track == null) {
            return;
        }
        maybeRecordLocalPlay();
        sendListeningEvent(
                track, completed ? "completed" : "skipped", reason, player.getCurrentPosition(), track.durationMs
        );
        currentTrack = null;
    }

    private void maybeRecordLocalPlay() {
        Track track = currentTrack;
        if (track == null || !track.local || track.localPlayCountRecorded || player == null) {
            return;
        }
        long duration = track.durationMs > 0 ? track.durationMs : player.getDuration();
        if (duration <= 0 || duration == C.TIME_UNSET) return;
        long position = Math.max(0L, player.getCurrentPosition());
        if (position < Math.round(duration * 0.9d)) return;
        track.localPlayCountRecorded = true;
        long localTrackId = track.localId;
        new Thread(() -> LocalLibraryDatabase.get(this).libraryDao()
                .recordCompletedPlay(localTrackId, System.currentTimeMillis()),
                "AdolarLocalPlayCount").start();
    }

    private void rememberCurrentTrack() {
        if (currentTrack == null) return;
        previousTracks.addLast(currentTrack);
        if (previousTracks.size() > 100) previousTracks.removeFirst();
    }

    private void sendListeningEvent(
            Track track, String eventType, String reason, long positionMs, long durationMs
    ) {
        if (track.local || sessionCookie().isEmpty()) {
            return;
        }
        final int sequence = eventSequence.incrementAndGet();
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                connection = openConnection(
                        AdolarPrefs.apiUrl(this) + "/api/adolar4u/events/" + track.id,
                        "POST"
                );
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                JSONObject payload = new JSONObject();
                payload.put("event_type", eventType);
                payload.put("source", "adolar4u".equals(currentStationEngine) ? "adolar4u" : "radio");
                if (reason != null) {
                    payload.put("reason", reason);
                }
                payload.put("position_seconds", positionMs / 1000.0);
                payload.put("duration_seconds", durationMs / 1000.0);
                payload.put("session_id", listeningSession);
                payload.put("client_event_id", listeningSession + ":" + sequence + ":" + eventType);
                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body);
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
                // Listening telemetry must never interrupt playback.
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        }, "AdolarListeningEvent").start();
    }

    private HttpURLConnection openConnection(String address, String method) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(8000);
        connection.setReadTimeout(8000);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("X-Adolar-Product", "android");
        String cookie = sessionCookie();
        if (!cookie.isEmpty()) {
            connection.setRequestProperty("Cookie", cookie);
        }
        return connection;
    }

    private boolean isSuccessful(HttpURLConnection connection) throws Exception {
        int status = connection.getResponseCode();
        return status >= 200 && status < 300;
    }

    private String sessionCookie() {
        String cookie = CookieManager.getInstance().getCookie(AdolarPrefs.apiUrl(this));
        return cookie == null ? "" : cookie;
    }

    private void sendConnectionHeartbeat(boolean playing, long position) {
        Log.d(TAG, "heartbeat tick, playing=" + playing + " position=" + position);
        HttpURLConnection connection = null;
        try {
            connection = openConnection(
                    AdolarPrefs.apiUrl(this) + "/api/client/heartbeat", "POST"
            );
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setDoOutput(true);
            JSONObject payload = new JSONObject();
            payload.put("product", "android");
            payload.put("client_id", listeningSession);
            byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body);
            }
            connection.getResponseCode();
        } catch (Exception ignored) {
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void updateMetadata(Track track) {
        String mediaId = track.local
                ? LOCAL_TRACK_PREFIX + track.localId
                : String.valueOf(track.id);
        MediaMetadataCompat.Builder builder = new MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID, mediaId)
                .putString(MediaMetadataCompat.METADATA_KEY_TITLE, track.title)
                .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, track.artist)
                .putString(MediaMetadataCompat.METADATA_KEY_ALBUM, track.album)
                .putLong(MediaMetadataCompat.METADATA_KEY_YEAR, track.year)
                .putString(METADATA_KEY_ADOLAR4U_REASON, track.reason)
                .putLong(METADATA_KEY_LASTFM_LOVED, track.loved ? 1L : 0L)
                .putLong(METADATA_KEY_HAS_LYRICS, track.hasLyrics ? 1L : 0L)
                .putString(MediaMetadataCompat.METADATA_KEY_DISPLAY_SUBTITLE, currentStationName)
                .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, track.durationMs);
        if (track.hasCover && !track.coverHash.isEmpty()) {
            builder.putString(
                    MediaMetadataCompat.METADATA_KEY_ALBUM_ART_URI,
                    AdolarPrefs.apiUrl(this) + "/api/cover/" + Uri.encode(track.coverHash) + "?full=1"
            );
        }
        mediaSession.setMetadata(builder.build());
    }

    private void requestLyricsIfMissing(Track track) {
        if (track == null || track.hasLyrics) return;
        final int trackId = track.id;
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                connection = openConnection(
                        AdolarPrefs.apiUrl(this) + "/api/tracks/" + trackId + "/lyrics/fetch",
                        "POST"
                );
                connection.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (connection != null) connection.disconnect();
            }
        }, "AdolarLyricsFetch").start();
    }

    private void updatePlaybackState(int state, String error) {
        long position = player.getCurrentPosition();
        PlaybackStateCompat.Builder builder = new PlaybackStateCompat.Builder()
                .setActions(
                        PlaybackStateCompat.ACTION_PLAY
                                | PlaybackStateCompat.ACTION_PAUSE
                                | PlaybackStateCompat.ACTION_PLAY_PAUSE
                                | PlaybackStateCompat.ACTION_SKIP_TO_NEXT
                                | PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS
                                | PlaybackStateCompat.ACTION_SEEK_TO
                                | PlaybackStateCompat.ACTION_SET_SHUFFLE_MODE
                                | PlaybackStateCompat.ACTION_STOP
                                | PlaybackStateCompat.ACTION_PLAY_FROM_MEDIA_ID
                )
                .setState(state, position, state == PlaybackStateCompat.STATE_PLAYING ? 1f : 0f);
        if (error != null) {
            builder.setErrorMessage(error);
        }
        mediaSession.setPlaybackState(builder.build());
        if (foregroundStarted) {
            // Reposting through the foreground-service API updates the existing
            // media notification and does not require POST_NOTIFICATIONS.
            startForeground(PLAYBACK_NOTIFICATION_ID, buildNotification());
        }
    }

    private void persistLocalPlayback(boolean active) {
        SharedPreferences.Editor editor = getSharedPreferences(
                LOCAL_PLAYBACK_PREFS, MODE_PRIVATE
        ).edit().putBoolean("active", active)
                .putInt("queue_index", localQueueIndex)
                .putString("queue_name", localQueueName)
                .putBoolean("shuffle_enabled", localShuffleEnabled)
                .putLong("position_ms", player == null ? 0L : player.getCurrentPosition());
        StringBuilder encoded = new StringBuilder(localQueueIds.size() * 8);
        for (int index = 0; index < localQueueIds.size(); index++) {
            if (index > 0) encoded.append(',');
            encoded.append(localQueueIds.get(index));
        }
        editor.putString("queue_ids", encoded.toString())
                .putString("original_queue_ids", encodeQueue(localQueueOriginalIds))
                .apply();
    }

    private void restoreLocalPlayback() {
        SharedPreferences preferences = getSharedPreferences(
                LOCAL_PLAYBACK_PREFS, MODE_PRIVATE
        );
        if (!preferences.getBoolean("active", false)) return;
        String encoded = preferences.getString("queue_ids", "");
        if (encoded == null || encoded.isEmpty()) return;
        localQueueIds.clear();
        for (String value : encoded.split(",")) {
            try {
                localQueueIds.add(Long.parseLong(value));
            } catch (NumberFormatException ignored) {
            }
        }
        localQueueIndex = preferences.getInt("queue_index", -1);
        if (localQueueIndex < 0 || localQueueIndex >= localQueueIds.size()) {
            localQueueIds.clear();
            localQueueIndex = -1;
            return;
        }
        localShuffleEnabled = preferences.getBoolean("shuffle_enabled", false);
        localQueueOriginalIds.clear();
        if (localShuffleEnabled) {
            decodeQueue(
                    preferences.getString("original_queue_ids", ""),
                    localQueueOriginalIds
            );
            if (localQueueOriginalIds.isEmpty()) {
                localQueueOriginalIds.addAll(localQueueIds);
            }
        }
        localQueueName = preferences.getString("queue_name", "Lokale Musik");
        localMode = true;
        publishLocalShuffleMode();
        currentStationName = localQueueName;
        currentStationEngine = "local";
        long positionMs = Math.max(0L, preferences.getLong("position_ms", 0L));
        loadLocalTrackById(
                localQueueIds.get(localQueueIndex), false, false, positionMs
        );
    }

    private String encodeQueue(List<Long> queue) {
        StringBuilder encoded = new StringBuilder(queue.size() * 8);
        for (int index = 0; index < queue.size(); index++) {
            if (index > 0) encoded.append(',');
            encoded.append(queue.get(index));
        }
        return encoded.toString();
    }

    private void decodeQueue(String encoded, List<Long> target) {
        if (encoded == null || encoded.isEmpty()) return;
        for (String value : encoded.split(",")) {
            try {
                target.add(Long.parseLong(value));
            } catch (NumberFormatException ignored) {
            }
        }
    }

    private String readAll(InputStream stream) throws Exception {
        StringBuilder body = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8)
        )) {
            String line;
            while ((line = reader.readLine()) != null) {
                body.append(line);
            }
        }
        return body.toString();
    }

    @Override
    public void onDestroy() {
        mainHandler.removeCallbacks(connectionHeartbeat);
        mainHandler.removeCallbacks(crossfadeMonitor);
        cancelCrossfade();
        playbackRequest++;
        if (localMode && currentTrack != null) persistLocalPlayback(true);
        finishCurrentTrack(false, "stop");
        player.release();
        preloadPlayer.release();
        // The process-wide SimpleCache intentionally survives service reconnects.
        // Android releases its files when the app process terminates.
        stopForeground(true);
        foregroundStarted = false;
        if (mediaSession != null) {
            mediaSession.release();
            mediaSession = null;
        }
        super.onDestroy();
    }

    private static final class Station {
        int id;
        String name;
        String description;
        String engine;
    }

    private static final class PageSpec {
        final int size;
        final int offset;

        PageSpec(int size, int offset) {
            this.size = size;
            this.offset = offset;
        }
    }

    private static final class BrowserLocalRequest {
        long trackId;
        String context;
    }

    private static final class Track {
        int id;
        long localId;
        boolean local;
        boolean localPlayCountRecorded;
        String localDocumentUri;
        String title;
        String artist;
        String album;
        int year;
        String reason;
        long durationMs;
        String coverHash;
        boolean hasCover;
        boolean hasLyrics;
        boolean loved;
        String streamVersion;
    }
}
