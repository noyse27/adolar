package net.polze.adolarradio;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
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
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.datasource.cache.CacheDataSource;
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor;
import androidx.media3.datasource.cache.SimpleCache;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.MediaSource;
import androidx.media3.exoplayer.source.ProgressiveMediaSource;

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
    private static final String STATION_PREFIX = "station:";
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
    private final ArrayDeque<Track> upcomingTracks = new ArrayDeque<>();
    private boolean queueRequestInFlight;
    private boolean crossfadeActive;
    private Runnable crossfadeStep;
    private long bufferingStartedMs;
    private int currentStationId = 1;
    private String currentStationName = "Adolar Radio";
    private String currentStationEngine = "shuffle";
    private int playbackRequest;
    private boolean foregroundStarted;

    private final Runnable crossfadeMonitor = new Runnable() {
        @Override
        public void run() {
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
            mainHandler.postDelayed(this, 30000);
        }
    };

    private final Player.Listener playerListener = new Player.Listener() {
        @Override
        public void onPlaybackStateChanged(int state) {
            if (state == Player.STATE_ENDED) {
                if (!crossfadeActive) {
                    finishCurrentTrack(true, "ended");
                    promotePreloadedTrack(false);
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
            promotePreloadedTrack(false);
        }
    };

    private final MediaSessionCompat.Callback mediaCallback = new MediaSessionCompat.Callback() {
        @Override
        public void onPlay() {
            if (player.getMediaItemCount() > 0) {
                player.play();
                return;
            }
            loadNextTrack();
        }

        @Override
        public void onPlayFromMediaId(String mediaId, Bundle extras) {
            Station station = parseStation(mediaId, extras);
            if (station == null) {
                updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Sender nicht gefunden.");
                return;
            }
            cancelCrossfade();
            clearPlayers();
            upcomingTracks.clear();
            preloadedTrack = null;
            finishCurrentTrack(false, "track_change");
            currentStationId = station.id;
            currentStationName = station.name;
            currentStationEngine = station.engine;
            AdolarPrefs.setStationId(AdolarMediaService.this, station.id);
            loadNextTrack();
        }

        @Override
        public void onPlayFromSearch(String query, Bundle extras) {
            // Adolar exposes stations rather than a finite song catalogue in the
            // car UI. A voice request therefore resumes the selected station.
            loadNextTrack();
        }

        @Override
        public void onSkipToNext() {
            cancelCrossfade();
            finishCurrentTrack(false, "manual_next");
            promotePreloadedTrack(false);
        }

        @Override
        public void onSkipToPrevious() {
            player.seekTo(0);
        }

        @Override
        public void onPause() {
            cancelCrossfade();
            player.pause();
        }

        @Override
        public void onStop() {
            playbackRequest++;
            cancelCrossfade();
            finishCurrentTrack(false, "stop");
            clearPlayers();
            upcomingTracks.clear();
            preloadedTrack = null;
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
        mediaSession = new MediaSessionCompat(this, "AdolarRadio");
        mediaSession.setFlags(
                MediaSessionCompat.FLAG_HANDLES_MEDIA_BUTTONS
                        | MediaSessionCompat.FLAG_HANDLES_TRANSPORT_CONTROLS
        );
        mediaSession.setCallback(mediaCallback);
        setSessionToken(mediaSession.getSessionToken());
        // STATE_NONE makes Android Auto's playback UI inaccessible. The service
        // has playable stations even before one is selected, so advertise an
        // idle but controllable session from the start.
        updatePlaybackState(PlaybackStateCompat.STATE_STOPPED, null);
        mainHandler.post(connectionHeartbeat);
        mainHandler.post(crossfadeMonitor);
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
        if (!ROOT_ID.equals(parentId)) {
            result.sendResult(new ArrayList<>());
            return;
        }
        if (!AdolarPrefs.hasServerUrl(this)) {
            List<MediaBrowserCompat.MediaItem> items = new ArrayList<>();
            MediaDescriptionCompat description = new MediaDescriptionCompat.Builder()
                    .setMediaId("setup-required")
                    .setTitle(getString(R.string.car_no_server))
                    .setSubtitle(getString(R.string.app_name))
                    .build();
            items.add(new MediaBrowserCompat.MediaItem(description, MediaBrowserCompat.MediaItem.FLAG_BROWSABLE));
            result.sendResult(items);
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
                        ? "Persönlicher Sender"
                        : station.description;
                MediaDescriptionCompat description = new MediaDescriptionCompat.Builder()
                        .setMediaId(STATION_PREFIX + station.id)
                        .setTitle(station.name)
                        .setSubtitle(subtitle == null || subtitle.isEmpty() ? getString(R.string.app_name) : subtitle)
                        .setExtras(extras)
                        .build();
                items.add(new MediaBrowserCompat.MediaItem(description, MediaBrowserCompat.MediaItem.FLAG_PLAYABLE));
                if (station.id == currentStationId) {
                    currentStationName = station.name;
                    currentStationEngine = station.engine;
                }
            }
            mainHandler.post(() -> result.sendResult(items));
        }, "AdolarStationLoader").start();
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
        currentTrack = track;
        mediaSession.setActive(true);
        updateMetadata(track);
        requestLyricsIfMissing(track);
        // Marks the service as "started" so it survives the phone UI unbinding
        // (e.g. screen off triggers MainActivity.onStop -> mediaBrowser.disconnect()).
        // Without this the service is bound-only and Android destroys it, and the
        // player with it, the moment the last bound client goes away.
        ContextCompat.startForegroundService(this, new Intent(this, AdolarMediaService.class));
        startForeground(PLAYBACK_NOTIFICATION_ID, buildNotification());
        foregroundStarted = true;
        player.setMediaSource(buildMediaSource(track));
        player.prepare();
        player.setPlayWhenReady(true);
        sendListeningEvent(track, "started", null, 0, track.durationMs);
        prepareNextTrack();
    }

    private MediaSource buildMediaSource(Track track) {
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
        if (queueRequestInFlight || !AdolarPrefs.hasServerUrl(this)) return;
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
        if (preloadedTrack != null) return;
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
        Intent contentIntent = new Intent(this, MainActivity.class);
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
        sendListeningEvent(
                track, completed ? "completed" : "skipped", reason, player.getCurrentPosition(), track.durationMs
        );
        currentTrack = null;
    }

    private void sendListeningEvent(
            Track track, String eventType, String reason, long positionMs, long durationMs
    ) {
        if (sessionCookie().isEmpty()) {
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
        MediaMetadataCompat.Builder builder = new MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID, String.valueOf(track.id))
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

    private static final class Track {
        int id;
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
