package net.polze.adolarradio;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.support.v4.media.MediaBrowserCompat;
import android.support.v4.media.MediaDescriptionCompat;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaSessionCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import android.webkit.CookieManager;
import android.view.KeyEvent;

import androidx.core.app.NotificationCompat;
import androidx.media.MediaBrowserServiceCompat;
import androidx.media.app.NotificationCompat.MediaStyle;
import androidx.media.session.MediaButtonReceiver;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

public class AdolarMediaService extends MediaBrowserServiceCompat {
    private static final String ROOT_ID = "adolar_root";
    private static final String STATION_PREFIX = "station:";
    static final String METADATA_KEY_ADOLAR4U_REASON =
            "net.polze.adolarradio.metadata.ADOLAR4U_REASON";
    static final String METADATA_KEY_LASTFM_LOVED =
            "net.polze.adolarradio.metadata.LASTFM_LOVED";
    private static final String PLAYBACK_CHANNEL_ID = "adolar_playback";
    private static final int PLAYBACK_NOTIFICATION_ID = 1001;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final String listeningSession = "android-auto-" + UUID.randomUUID();
    private final AtomicInteger eventSequence = new AtomicInteger();
    private MediaSessionCompat mediaSession;
    private MediaPlayer player;
    private AudioManager audioManager;
    private AudioFocusRequest audioFocusRequest;
    private Track currentTrack;
    private int currentStationId = 1;
    private String currentStationName = "Adolar Radio";
    private String currentStationEngine = "shuffle";
    private int playbackRequest;
    private boolean foregroundStarted;
    private boolean resumeOnAudioFocusGain;
    private final Runnable connectionHeartbeat = new Runnable() {
        @Override
        public void run() {
            if (AdolarPrefs.hasServerUrl(AdolarMediaService.this)) {
                new Thread(
                        AdolarMediaService.this::sendConnectionHeartbeat,
                        "AdolarConnectionHeartbeat"
                ).start();
            }
            mainHandler.postDelayed(this, 30000);
        }
    };

    private final BroadcastReceiver noisyAudioReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(intent.getAction())) {
                mediaCallback.onPause();
            }
        }
    };

    private final MediaSessionCompat.Callback mediaCallback = new MediaSessionCompat.Callback() {
        @Override
        public void onPlay() {
            if (player != null && currentTrack != null) {
                if (!requestAudioFocus()) {
                    updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Audiofokus nicht verfügbar.");
                    return;
                }
                resumeOnAudioFocusGain = false;
                player.start();
                updatePlaybackState(PlaybackStateCompat.STATE_PLAYING, null);
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
            finishCurrentTrack(false, "manual_next");
            loadNextTrack();
        }

        @Override
        public void onSkipToPrevious() {
            if (player != null) {
                player.seekTo(0);
                updatePlaybackState(
                        player.isPlaying() ? PlaybackStateCompat.STATE_PLAYING : PlaybackStateCompat.STATE_PAUSED,
                        null
                );
            }
        }

        @Override
        public void onPause() {
            resumeOnAudioFocusGain = false;
            if (player != null && player.isPlaying()) {
                player.pause();
                updatePlaybackState(PlaybackStateCompat.STATE_PAUSED, null);
            }
        }

        @Override
        public void onStop() {
            resumeOnAudioFocusGain = false;
            playbackRequest++;
            finishCurrentTrack(false, "stop");
            releasePlayer();
            abandonAudioFocus();
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
        audioManager = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        IntentFilter noisyFilter = new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(noisyAudioReceiver, noisyFilter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(noisyAudioReceiver, noisyFilter);
        }
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
        final int request = ++playbackRequest;
        updatePlaybackState(PlaybackStateCompat.STATE_BUFFERING, null);
        new Thread(() -> {
            Track track = fetchStationTrack(currentStationId);
            mainHandler.post(() -> {
                if (request != playbackRequest) {
                    return;
                }
                if (track == null) {
                    updatePlaybackState(
                            PlaybackStateCompat.STATE_ERROR,
                            "Sender nicht verfügbar. Für Adolar4U bitte in der Handy-App anmelden."
                    );
                } else {
                    startTrack(track);
                }
            });
        }, "AdolarTrackLoader").start();
    }

    private Track fetchStationTrack(int stationId) {
        HttpURLConnection connection = null;
        try {
            Uri.Builder urlBuilder = Uri.parse(
                    AdolarPrefs.apiUrl(this) + "/api/radio-stations/" + stationId + "/tracks"
            ).buildUpon().appendQueryParameter("count", "1");
            String shuffleSession = AdolarPrefs.getShuffleSession(this, stationId);
            if (!shuffleSession.isEmpty()) {
                urlBuilder.appendQueryParameter("shuffle_session", shuffleSession);
            }
            connection = openConnection(urlBuilder.build().toString(), "GET");
            if (!isSuccessful(connection)) {
                return null;
            }
            String nextSession = connection.getHeaderField("X-Shuffle-Session");
            if (nextSession != null && !nextSession.isEmpty()) {
                AdolarPrefs.setShuffleSession(this, stationId, nextSession);
            }
            JSONArray tracks = new JSONArray(readAll(connection.getInputStream()));
            if (tracks.length() == 0) {
                return null;
            }
            JSONObject item = tracks.getJSONObject(0);
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
            return track;
        } catch (Exception ignored) {
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void startTrack(Track track) {
        final int trackRequest = playbackRequest;
        releasePlayer();
        currentTrack = track;
        mediaSession.setActive(true);
        updateMetadata(track);
        startForeground(PLAYBACK_NOTIFICATION_ID, buildNotification());
        foregroundStarted = true;
        player = new MediaPlayer();
        try {
            player.setAudioAttributes(new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .build());
            player.setWakeMode(this, PowerManager.PARTIAL_WAKE_LOCK);
            Map<String, String> headers = new HashMap<>();
            String cookie = sessionCookie();
            if (!cookie.isEmpty()) {
                headers.put("Cookie", cookie);
            }
            player.setDataSource(
                    this,
                    Uri.parse(AdolarPrefs.apiUrl(this) + "/api/stream/" + track.id),
                    headers
            );
            player.setOnPreparedListener(mediaPlayer -> {
                if (!requestAudioFocus()) {
                    finishCurrentTrack(false, "error");
                    releasePlayer();
                    updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Audiofokus nicht verfügbar.");
                    stopForeground(true);
                    foregroundStarted = false;
                    return;
                }
                resumeOnAudioFocusGain = false;
                mediaPlayer.start();
                sendListeningEvent(track, "started", null, 0, track.durationMs);
                updatePlaybackState(PlaybackStateCompat.STATE_PLAYING, null);
            });
            player.setOnCompletionListener(mediaPlayer -> {
                finishCurrentTrack(true, "ended");
                loadNextTrack();
            });
            player.setOnErrorListener((mediaPlayer, what, extra) -> {
                finishCurrentTrack(false, "error");
                releasePlayer();
                updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Wiedergabe fehlgeschlagen. Nächster Titel wird geladen.");
                retryCurrentRequestAfterDelay(trackRequest);
                return true;
            });
            player.prepareAsync();
        } catch (Exception exception) {
            releasePlayer();
            updatePlaybackState(PlaybackStateCompat.STATE_ERROR, "Stream konnte nicht gestartet werden.");
            retryCurrentRequestAfterDelay(playbackRequest);
        }
    }

    private void retryCurrentRequestAfterDelay(int failedRequest) {
        mainHandler.postDelayed(() -> {
            if (failedRequest == playbackRequest && mediaSession != null) {
                loadNextTrack();
            }
        }, 1500);
    }

    private final AudioManager.OnAudioFocusChangeListener audioFocusListener = focusChange -> {
        if (player == null) {
            return;
        }
        if (focusChange == AudioManager.AUDIOFOCUS_LOSS) {
            resumeOnAudioFocusGain = false;
            if (player.isPlaying()) {
                player.pause();
            }
            updatePlaybackState(PlaybackStateCompat.STATE_PAUSED, null);
            abandonAudioFocus();
        } else if (focusChange == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) {
            if (player.isPlaying()) {
                resumeOnAudioFocusGain = true;
                player.pause();
                updatePlaybackState(PlaybackStateCompat.STATE_PAUSED, null);
            }
        } else if (focusChange == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
            player.setVolume(0.25f, 0.25f);
        } else if (focusChange == AudioManager.AUDIOFOCUS_GAIN) {
            player.setVolume(1f, 1f);
            if (resumeOnAudioFocusGain) {
                resumeOnAudioFocusGain = false;
                player.start();
                updatePlaybackState(PlaybackStateCompat.STATE_PLAYING, null);
            }
        }
    };

    private boolean requestAudioFocus() {
        if (audioManager == null) {
            return false;
        }
        int result;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (audioFocusRequest == null) {
                audioFocusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                        .setAudioAttributes(new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                                .build())
                        .setOnAudioFocusChangeListener(audioFocusListener, mainHandler)
                        .build();
            }
            result = audioManager.requestAudioFocus(audioFocusRequest);
        } else {
            result = audioManager.requestAudioFocus(
                    audioFocusListener, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN
            );
        }
        return result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
    }

    private void abandonAudioFocus() {
        if (audioManager == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && audioFocusRequest != null) {
            audioManager.abandonAudioFocusRequest(audioFocusRequest);
        } else {
            audioManager.abandonAudioFocus(audioFocusListener);
        }
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
        return new NotificationCompat.Builder(this, PLAYBACK_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_car_attribution)
                .setContentTitle(title)
                .setContentText(artist)
                .setSubText(currentStationName)
                .setContentIntent(contentPendingIntent)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setOnlyAlertOnce(true)
                .setOngoing(player != null && player.isPlaying())
                .addAction(mediaAction(KeyEvent.KEYCODE_MEDIA_PREVIOUS, android.R.drawable.ic_media_previous, "Zurück"))
                .addAction(mediaAction(
                        player != null && player.isPlaying() ? KeyEvent.KEYCODE_MEDIA_PAUSE : KeyEvent.KEYCODE_MEDIA_PLAY,
                        player != null && player.isPlaying() ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                        player != null && player.isPlaying() ? "Pause" : "Wiedergabe"
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
        long position = 0;
        if (player != null) {
            try {
                position = player.getCurrentPosition();
            } catch (IllegalStateException ignored) {
                position = 0;
            }
        }
        sendListeningEvent(track, completed ? "completed" : "skipped", reason, position, track.durationMs);
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

    private void sendConnectionHeartbeat() {
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

    private void releasePlayer() {
        if (player != null) {
            player.reset();
            player.release();
            player = null;
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

    private void updatePlaybackState(int state, String error) {
        long position = PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN;
        if (player != null) {
            try {
                position = player.getCurrentPosition();
            } catch (IllegalStateException ignored) {
                position = PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN;
            }
        }
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
        playbackRequest++;
        resumeOnAudioFocusGain = false;
        finishCurrentTrack(false, "stop");
        releasePlayer();
        abandonAudioFocus();
        stopForeground(true);
        foregroundStarted = false;
        unregisterReceiver(noisyAudioReceiver);
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
        boolean loved;
    }
}
