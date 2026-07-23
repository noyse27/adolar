package net.polze.adolarradio;

import android.app.Activity;
import android.content.ComponentName;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.support.v4.media.MediaBrowserCompat;
import android.support.v4.media.MediaDescriptionCompat;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaControllerCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.core.content.res.ResourcesCompat;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Native phone controller for the same MediaSession used by Android Auto.
 * Playback deliberately lives only in {@link AdolarMediaService}; the Activity
 * can disappear without creating a second player or interrupting the queue.
 */
public class MainActivity extends Activity {
    private static final String ROOT_ID = "adolar_root";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private MediaBrowserCompat mediaBrowser;
    private MediaControllerCompat mediaController;
    private boolean showingSettings;
    private boolean subscribed;
    private boolean browserConnecting;
    private int coverGeneration;
    private int accountGeneration;
    private int trackActionGeneration;

    private Spinner stationSpinner;
    private TextView trackTitle;
    private TextView trackArtist;
    private TextView trackAlbum;
    private TextView trackReason;
    private TextView playbackStatus;
    private TextView selectedStationLabel;
    private ImageView coverView;
    private Button playPauseButton;
    private Button previousButton;
    private Button nextButton;
    private Button stopButton;
    private Button accountButton;
    private Button favoriteButton;
    private Button loveButton;
    private boolean signedIn;
    private String signedInUsername = "";
    private boolean lastFmConnected;
    private boolean favorite;
    private boolean loved;
    private int currentTrackId = -1;
    private String currentTrackTitle = "";
    private String currentTrackArtist = "";
    private Typeface orbitronMedium;
    private Typeface orbitronBold;
    private final List<StationItem> stations = new ArrayList<>();
    private StationItem selectedStation;

    private final MediaBrowserCompat.ConnectionCallback connectionCallback =
            new MediaBrowserCompat.ConnectionCallback() {
                @Override
                public void onConnected() {
                    browserConnecting = false;
                    try {
                        mediaController = new MediaControllerCompat(
                                MainActivity.this, mediaBrowser.getSessionToken()
                        );
                        MediaControllerCompat.setMediaController(MainActivity.this, mediaController);
                        mediaController.registerCallback(controllerCallback);
                        subscribeToStations();
                        refreshControllerUi();
                    } catch (Exception exception) {
                        setStatus(getString(R.string.status_connection_error), true);
                    }
                }

                @Override
                public void onConnectionSuspended() {
                    browserConnecting = false;
                    setStatus(getString(R.string.status_connection_lost), true);
                    setControlsEnabled(false);
                }

                @Override
                public void onConnectionFailed() {
                    browserConnecting = false;
                    setStatus(getString(R.string.status_connection_error), true);
                    setControlsEnabled(false);
                }
            };

    private final MediaBrowserCompat.SubscriptionCallback subscriptionCallback =
            new MediaBrowserCompat.SubscriptionCallback() {
                @Override
                public void onChildrenLoaded(
                        String parentId, List<MediaBrowserCompat.MediaItem> children
                ) {
                    stations.clear();
                    for (MediaBrowserCompat.MediaItem item : children) {
                        if (item.isPlayable()) {
                            stations.add(new StationItem(item.getDescription()));
                        }
                    }
                    showStations();
                }

                @Override
                public void onError(String parentId) {
                    setStatus(getString(R.string.status_station_error), true);
                }
            };

    private final MediaControllerCompat.Callback controllerCallback =
            new MediaControllerCompat.Callback() {
                @Override
                public void onPlaybackStateChanged(PlaybackStateCompat state) {
                    updatePlaybackState(state);
                }

                @Override
                public void onMetadataChanged(MediaMetadataCompat metadata) {
                    updateMetadata(metadata);
                }

                @Override
                public void onSessionDestroyed() {
                    setStatus(getString(R.string.status_connection_lost), true);
                    setControlsEnabled(false);
                }
            };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        orbitronMedium = ResourcesCompat.getFont(this, R.font.orbitron_medium);
        orbitronBold = ResourcesCompat.getFont(this, R.font.orbitron_bold);
        if (AdolarPrefs.hasServerUrl(this)) {
            showPlayer();
        } else {
            showSettings();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (AdolarPrefs.hasServerUrl(this)) {
            connectBrowser();
        }
    }

    @Override
    protected void onStop() {
        detachController();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        coverGeneration++;
        disconnectBrowser();
        super.onDestroy();
    }

    private void showPlayer() {
        showingSettings = false;

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(getColorCompat(R.color.bg_tertiary));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(20), dp(18), dp(20), dp(24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(header, matchWrap());

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.ic_launcher_foreground);
        logo.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(42), dp(42));
        logoParams.setMargins(0, 0, dp(8), 0);
        header.addView(logo, logoParams);

        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams brandParams = new LinearLayout.LayoutParams(0, dp(62), 1f);
        header.addView(brand, brandParams);

        TextView title = new TextView(this);
        title.setText(getString(R.string.app_name));
        title.setTextColor(getColorCompat(R.color.accent_light));
        title.setTextSize(24);
        title.setGravity(Gravity.START);
        title.setTypeface(orbitronBold);
        title.setLetterSpacing(0.08f);
        brand.addView(title, matchWrap());

        TextView version = new TextView(this);
        version.setText(getString(R.string.version_format, BuildConfig.VERSION_NAME));
        version.setTextColor(getColorCompat(R.color.text_secondary));
        version.setTextSize(10);
        version.setTypeface(orbitronMedium);
        version.setLetterSpacing(0.05f);
        brand.addView(version, matchWrap());

        accountButton = compactHeaderButton(R.drawable.ic_person_outline);
        accountButton.setContentDescription(getString(R.string.login));
        accountButton.setOnClickListener(view -> showAccountMenu());
        LinearLayout.LayoutParams accountParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(44)
        );
        accountParams.setMargins(0, 0, dp(6), 0);
        header.addView(accountButton, accountParams);

        Button settingsButton = compactHeaderButton(R.drawable.ic_settings_outline);
        settingsButton.setContentDescription(getString(R.string.settings_button));
        settingsButton.setOnClickListener(view -> showSettings());
        header.addView(settingsButton, new LinearLayout.LayoutParams(dp(44), dp(44)));

        selectedStationLabel = label(getString(R.string.station_label), 12, R.color.text_secondary);
        LinearLayout.LayoutParams stationLabelParams = matchWrap();
        stationLabelParams.setMargins(0, dp(18), 0, dp(4));
        root.addView(selectedStationLabel, stationLabelParams);

        stationSpinner = new Spinner(this);
        stationSpinner.setEnabled(false);
        stationSpinner.setPadding(dp(10), 0, dp(10), 0);
        stationSpinner.setBackground(roundedRipple(
                getColorCompat(R.color.bg_primary),
                getColorCompat(R.color.border_subtle),
                dp(9),
                getColorCompat(R.color.accent)
        ));
        root.addView(stationSpinner, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)
        ));

        coverView = new ImageView(this);
        coverView.setScaleType(ImageView.ScaleType.CENTER_CROP);
        coverView.setBackgroundColor(getColorCompat(R.color.bg_primary));
        coverView.setBackground(roundedShape(
                getColorCompat(R.color.bg_primary), Color.TRANSPARENT, dp(10)
        ));
        coverView.setClipToOutline(true);
        coverView.setImageResource(R.drawable.ic_launcher_foreground);
        int coverSize = Math.min(
                dp(360), getResources().getDisplayMetrics().widthPixels - dp(40)
        );
        LinearLayout.LayoutParams coverParams = new LinearLayout.LayoutParams(coverSize, coverSize);
        coverParams.setMargins(0, dp(18), 0, dp(16));
        root.addView(coverView, coverParams);

        trackTitle = label(getString(R.string.no_track_title), 24, R.color.text_primary);
        trackTitle.setGravity(Gravity.CENTER);
        trackTitle.setMaxLines(2);
        trackTitle.setTypeface(Typeface.create("sans-serif", Typeface.BOLD));
        root.addView(trackTitle, matchWrap());

        trackArtist = label(getString(R.string.no_track_artist), 17, R.color.text_secondary);
        trackArtist.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams artistParams = matchWrap();
        artistParams.setMargins(0, dp(4), 0, 0);
        root.addView(trackArtist, artistParams);

        trackAlbum = label("", 13, R.color.text_secondary);
        trackAlbum.setGravity(Gravity.CENTER);
        trackAlbum.setMaxLines(2);
        LinearLayout.LayoutParams albumParams = matchWrap();
        albumParams.setMargins(0, dp(4), 0, 0);
        root.addView(trackAlbum, albumParams);

        trackReason = label("", 12, R.color.accent_light);
        trackReason.setGravity(Gravity.CENTER);
        trackReason.setMaxLines(2);
        LinearLayout.LayoutParams reasonParams = matchWrap();
        reasonParams.setMargins(0, dp(5), 0, dp(14));
        root.addView(trackReason, reasonParams);

        playbackStatus = label(getString(R.string.status_connecting), 14, R.color.accent_light);
        playbackStatus.setGravity(Gravity.CENTER);
        playbackStatus.setPadding(dp(10), dp(10), dp(10), dp(10));
        playbackStatus.setBackground(roundedShape(
                Color.rgb(48, 45, 78),
                getColorCompat(R.color.accent_deep),
                dp(99)
        ));
        root.addView(playbackStatus, matchWrap());

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        controls.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams controlsParams = matchWrap();
        controlsParams.setMargins(0, dp(12), 0, 0);
        root.addView(controls, controlsParams);

        previousButton = controlButton(getString(R.string.previous), false, false, view -> previous());
        playPauseButton = controlButton(getString(R.string.play), true, false, view -> playPause());
        nextButton = controlButton(getString(R.string.next), false, false, view -> next());
        stopButton = controlButton(getString(R.string.stop), false, true, view -> stop());
        controls.addView(previousButton, controlParams(54, 3));
        controls.addView(playPauseButton, controlParams(66, 7));
        controls.addView(nextButton, controlParams(54, 3));
        controls.addView(stopButton, controlParams(54, 3));
        setControlsEnabled(false);

        LinearLayout trackActions = new LinearLayout(this);
        trackActions.setOrientation(LinearLayout.HORIZONTAL);
        trackActions.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams trackActionsParams = matchWrap();
        trackActionsParams.setMargins(0, dp(12), 0, 0);
        root.addView(trackActions, trackActionsParams);

        favoriteButton = trackActionButton(getString(R.string.favorite_off), view -> toggleFavorite());
        loveButton = trackActionButton(getString(R.string.love_off), view -> toggleLove());
        LinearLayout.LayoutParams favoriteParams = new LinearLayout.LayoutParams(0, dp(46), 1f);
        favoriteParams.setMargins(0, 0, dp(5), 0);
        trackActions.addView(favoriteButton, favoriteParams);
        LinearLayout.LayoutParams loveParams = new LinearLayout.LayoutParams(0, dp(46), 1f);
        loveParams.setMargins(dp(5), 0, 0, 0);
        trackActions.addView(loveButton, loveParams);
        updateAccountButton();
        updateTrackActionButtons();

        setContentView(scroll);
        applySystemBarInsets(scroll);
        if (!stations.isEmpty()) {
            // showPlayer() creates a fresh Spinner when returning from settings.
            // Rebind the already loaded station list instead of waiting for a
            // MediaBrowser subscription callback that may not fire again.
            showStations();
        } else if (mediaBrowser != null && mediaBrowser.isConnected()) {
            subscribeToStations();
        }
        refreshControllerUi();
        refreshAccountAndTrackActions();
    }

    private void showSettings() {
        showingSettings = true;

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(getColorCompat(R.color.bg_tertiary));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(24), dp(24), dp(24), dp(24));
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        TextView title = label(getString(R.string.settings_title), 28, R.color.accent_light);
        title.setGravity(Gravity.CENTER);
        title.setTypeface(orbitronBold);
        title.setLetterSpacing(0.08f);
        root.addView(title, matchWrap());

        TextView subtitle = label(
                getString(R.string.settings_version_format, BuildConfig.VERSION_NAME),
                14,
                R.color.text_secondary
        );
        subtitle.setGravity(Gravity.CENTER);
        subtitle.setPadding(0, dp(2), 0, dp(30));
        root.addView(subtitle, matchWrap());

        TextView urlLabel = label(getString(R.string.server_url_label), 12, R.color.text_secondary);
        root.addView(urlLabel, matchWrap());

        EditText urlInput = new EditText(this);
        urlInput.setSingleLine(true);
        urlInput.setText(AdolarPrefs.getServerUrl(this));
        urlInput.setHint(getString(R.string.server_url_hint));
        urlInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlInput.setImeOptions(EditorInfo.IME_ACTION_DONE);
        urlInput.setTextColor(getColorCompat(R.color.text_primary));
        urlInput.setHintTextColor(getColorCompat(R.color.text_secondary));
        urlInput.setTextSize(15);
        urlInput.setPadding(dp(12), 0, dp(12), 0);
        root.addView(urlInput, inputParams());

        TextView error = label(getString(R.string.invalid_url), 12, R.color.text_secondary);
        error.setTextColor(Color.rgb(224, 62, 62));
        error.setVisibility(View.GONE);
        root.addView(error, matchWrap());

        TextView accountLabel = label(getString(R.string.account_label), 12, R.color.text_secondary);
        LinearLayout.LayoutParams accountLabelParams = matchWrap();
        accountLabelParams.setMargins(0, dp(16), 0, 0);
        root.addView(accountLabel, accountLabelParams);

        TextView accountStatus = label(
                getString(R.string.account_checking), 14, R.color.text_primary
        );
        LinearLayout.LayoutParams accountStatusParams = matchWrap();
        accountStatusParams.setMargins(0, dp(6), 0, dp(2));
        root.addView(accountStatus, accountStatusParams);

        EditText usernameInput = new EditText(this);
        usernameInput.setSingleLine(true);
        usernameInput.setHint(getString(R.string.username_hint));
        usernameInput.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_NORMAL
        );
        styleInput(usernameInput);
        root.addView(usernameInput, inputParams());

        EditText passwordInput = new EditText(this);
        passwordInput.setSingleLine(true);
        passwordInput.setHint(getString(R.string.password_hint));
        passwordInput.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
        );
        passwordInput.setImeOptions(EditorInfo.IME_ACTION_DONE);
        styleInput(passwordInput);
        root.addView(passwordInput, inputParams());

        TextView loginError = label("", 12, R.color.text_secondary);
        loginError.setTextColor(Color.rgb(224, 62, 62));
        loginError.setVisibility(View.GONE);
        root.addView(loginError, matchWrap());

        Button loginButton = new Button(this);
        loginButton.setText(getString(R.string.login));
        loginButton.setAllCaps(false);
        stylePrimaryAction(loginButton);
        root.addView(loginButton, buttonParams());

        Button logoutButton = new Button(this);
        logoutButton.setText(getString(R.string.logout));
        logoutButton.setAllCaps(false);
        styleSecondaryAction(logoutButton);
        logoutButton.setVisibility(View.GONE);
        root.addView(logoutButton, buttonParams());

        Button save = new Button(this);
        save.setText(getString(R.string.save_and_start));
        save.setAllCaps(false);
        stylePrimaryAction(save);
        root.addView(save, buttonParams());

        if (AdolarPrefs.hasServerUrl(this)) {
            Button cancel = new Button(this);
            cancel.setText(getString(R.string.back_to_player));
            cancel.setAllCaps(false);
            styleSecondaryAction(cancel);
            LinearLayout.LayoutParams cancelParams = buttonParams();
            cancelParams.setMargins(0, dp(8), 0, 0);
            root.addView(cancel, cancelParams);
            cancel.setOnClickListener(view -> showPlayer());
        }

        TextView hint = label(getString(R.string.settings_hint), 12, R.color.text_secondary);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(0, dp(12), 0, 0);
        root.addView(hint, matchWrap());

        View.OnClickListener saveAction = view -> {
            String url = urlInput.getText().toString();
            if (!AdolarPrefs.isValidServerUrl(url)) {
                error.setVisibility(View.VISIBLE);
                return;
            }
            boolean changed = !AdolarPrefs.normalizeUrl(url).equals(AdolarPrefs.getServerUrl(this));
            if (changed && mediaController != null) {
                mediaController.getTransportControls().stop();
            }
            AdolarPrefs.setServerUrl(this, url);
            if (changed) {
                disconnectBrowser();
                connectBrowser();
            }
            showPlayer();
        };
        save.setOnClickListener(saveAction);
        View.OnClickListener loginAction = view -> {
            String url = urlInput.getText().toString();
            if (!AdolarPrefs.isValidServerUrl(url)) {
                error.setVisibility(View.VISIBLE);
                return;
            }
            boolean changed = !AdolarPrefs.normalizeUrl(url).equals(AdolarPrefs.getServerUrl(this));
            AdolarPrefs.setServerUrl(this, url);
            if (changed) {
                disconnectBrowser();
                connectBrowser();
            }
            login(usernameInput.getText().toString(), passwordInput.getText().toString(),
                    accountStatus, usernameInput, passwordInput, loginButton, logoutButton,
                    loginError);
        };
        loginButton.setOnClickListener(loginAction);
        logoutButton.setOnClickListener(view -> logout(() -> showSettings()));
        urlInput.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                saveAction.onClick(save);
                return true;
            }
            return false;
        });
        passwordInput.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                loginAction.onClick(loginButton);
                return true;
            }
            return false;
        });

        setContentView(scroll);
        applySystemBarInsets(scroll);
        updateAccountSettings(
                accountStatus, usernameInput, passwordInput, loginButton, logoutButton
        );
        refreshAccount(() -> updateAccountSettings(
                accountStatus, usernameInput, passwordInput, loginButton, logoutButton
        ));
    }

    private void connectBrowser() {
        if (mediaBrowser != null && (mediaBrowser.isConnected() || browserConnecting)) {
            return;
        }
        mediaBrowser = new MediaBrowserCompat(
                this,
                new ComponentName(this, AdolarMediaService.class),
                connectionCallback,
                null
        );
        browserConnecting = true;
        mediaBrowser.connect();
        setStatus(getString(R.string.status_connecting), false);
    }

    private void subscribeToStations() {
        if (mediaBrowser == null || !mediaBrowser.isConnected()) {
            return;
        }
        if (subscribed) {
            mediaBrowser.unsubscribe(ROOT_ID, subscriptionCallback);
        }
        mediaBrowser.subscribe(ROOT_ID, subscriptionCallback);
        subscribed = true;
    }

    private void detachController() {
        if (mediaController != null) {
            mediaController.unregisterCallback(controllerCallback);
            mediaController = null;
        }
        MediaControllerCompat.setMediaController(this, null);
        if (mediaBrowser != null && mediaBrowser.isConnected() && subscribed) {
            mediaBrowser.unsubscribe(ROOT_ID, subscriptionCallback);
            subscribed = false;
        }
        if (mediaBrowser != null) {
            mediaBrowser.disconnect();
            mediaBrowser = null;
        }
        browserConnecting = false;
    }

    private void disconnectBrowser() {
        detachController();
    }

    private void showStations() {
        if (stationSpinner == null) {
            return;
        }
        StationAdapter adapter = new StationAdapter(stations);
        stationSpinner.setAdapter(adapter);
        stationSpinner.setEnabled(!stations.isEmpty());
        selectedStation = null;

        int selectedIndex = 0;
        int preferredId = AdolarPrefs.getStationId(this);
        for (int index = 0; index < stations.size(); index++) {
            if (stations.get(index).id == preferredId) {
                selectedIndex = index;
                break;
            }
        }
        stationSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                selectedStation = stations.get(position);
                updateSelectedStationLabel();
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
                selectedStation = null;
                updateSelectedStationLabel();
            }
        });
        if (!stations.isEmpty()) {
            stationSpinner.setSelection(selectedIndex);
            selectedStation = stations.get(selectedIndex);
            updateSelectedStationLabel();
            setControlsEnabled(mediaController != null);
        } else {
            setStatus(getString(R.string.status_no_stations), true);
            setControlsEnabled(false);
        }
    }

    private void refreshControllerUi() {
        if (mediaController == null) {
            return;
        }
        updateMetadata(mediaController.getMetadata());
        updatePlaybackState(mediaController.getPlaybackState());
        setControlsEnabled(!stations.isEmpty());
    }

    private void updateMetadata(MediaMetadataCompat metadata) {
        if (trackTitle == null) {
            return;
        }
        if (metadata == null) {
            currentTrackId = -1;
            currentTrackTitle = "";
            currentTrackArtist = "";
            trackTitle.setText(R.string.no_track_title);
            trackArtist.setText(R.string.no_track_artist);
            trackAlbum.setText("");
            trackReason.setText("");
            showCover(null);
            updateTrackActionButtons();
            return;
        }
        try {
            currentTrackId = Integer.parseInt(valueOrFallback(
                    metadata.getString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID), "-1"
            ));
        } catch (NumberFormatException ignored) {
            currentTrackId = -1;
        }
        currentTrackTitle = valueOrFallback(
                metadata.getString(MediaMetadataCompat.METADATA_KEY_TITLE), ""
        );
        currentTrackArtist = valueOrFallback(
                metadata.getString(MediaMetadataCompat.METADATA_KEY_ARTIST), ""
        );
        loved = metadata.getLong(AdolarMediaService.METADATA_KEY_LASTFM_LOVED) == 1L;
        trackTitle.setText(valueOrFallback(
                metadata.getString(MediaMetadataCompat.METADATA_KEY_TITLE),
                getString(R.string.no_track_title)
        ));
        trackArtist.setText(valueOrFallback(
                metadata.getString(MediaMetadataCompat.METADATA_KEY_ARTIST),
                getString(R.string.no_track_artist)
        ));
        String album = valueOrFallback(
                metadata.getString(MediaMetadataCompat.METADATA_KEY_ALBUM), ""
        );
        long year = metadata.getLong(MediaMetadataCompat.METADATA_KEY_YEAR);
        if (!album.isEmpty() && year > 0) {
            trackAlbum.setText(getString(R.string.album_year_format, album, year));
        } else if (!album.isEmpty()) {
            trackAlbum.setText(album);
        } else if (year > 0) {
            trackAlbum.setText(String.valueOf(year));
        } else {
            trackAlbum.setText("");
        }
        trackReason.setText(valueOrFallback(
                metadata.getString(AdolarMediaService.METADATA_KEY_ADOLAR4U_REASON), ""
        ));
        showCover(metadata.getString(MediaMetadataCompat.METADATA_KEY_ALBUM_ART_URI));
        refreshTrackActions();
    }

    private void updatePlaybackState(PlaybackStateCompat state) {
        if (playPauseButton == null) {
            return;
        }
        int stateCode = state == null ? PlaybackStateCompat.STATE_NONE : state.getState();
        boolean playing = stateCode == PlaybackStateCompat.STATE_PLAYING;
        playPauseButton.setText(playing ? R.string.pause : R.string.play);

        switch (stateCode) {
            case PlaybackStateCompat.STATE_PLAYING:
                setStatus(getString(R.string.status_playing), false);
                break;
            case PlaybackStateCompat.STATE_PAUSED:
                setStatus(getString(R.string.status_paused), false);
                break;
            case PlaybackStateCompat.STATE_BUFFERING:
            case PlaybackStateCompat.STATE_CONNECTING:
                setStatus(getString(R.string.status_buffering), false);
                break;
            case PlaybackStateCompat.STATE_ERROR:
                String message = state == null || state.getErrorMessage() == null
                        ? getString(R.string.status_playback_error)
                        : state.getErrorMessage().toString();
                setStatus(message, true);
                break;
            case PlaybackStateCompat.STATE_STOPPED:
                setStatus(getString(R.string.status_stopped), false);
                break;
            default:
                setStatus(getString(R.string.status_ready), false);
                break;
        }
    }

    private void playPause() {
        if (mediaController == null || selectedStation == null) {
            setStatus(getString(R.string.status_not_connected), true);
            return;
        }
        PlaybackStateCompat state = mediaController.getPlaybackState();
        if (state != null && state.getState() == PlaybackStateCompat.STATE_PLAYING) {
            mediaController.getTransportControls().pause();
            return;
        }
        if (AdolarPrefs.getStationId(this) != selectedStation.id || mediaController.getMetadata() == null) {
            mediaController.getTransportControls().playFromMediaId(
                    selectedStation.mediaId, selectedStation.extras
            );
        } else {
            mediaController.getTransportControls().play();
        }
    }

    private void previous() {
        if (mediaController != null) {
            mediaController.getTransportControls().skipToPrevious();
        }
    }

    private void next() {
        if (mediaController != null) {
            mediaController.getTransportControls().skipToNext();
        }
    }

    private void stop() {
        if (mediaController != null) {
            mediaController.getTransportControls().stop();
        }
    }

    private void showAccountMenu() {
        if (!signedIn) {
            showSettings();
            return;
        }
        PopupMenu menu = new PopupMenu(this, accountButton);
        menu.getMenu().add(getString(R.string.logout));
        menu.setOnMenuItemClickListener(item -> {
            logout(null);
            return true;
        });
        menu.show();
    }

    private void refreshAccountAndTrackActions() {
        refreshAccount(() -> {
            updateAccountButton();
            refreshTrackActions();
        });
    }

    private void refreshAccount(Runnable after) {
        if (!AdolarPrefs.hasServerUrl(this)) {
            signedIn = false;
            signedInUsername = "";
            if (after != null) after.run();
            return;
        }
        final int generation = ++accountGeneration;
        new Thread(() -> {
            ApiResponse response = requestApi("/api/me-optional", "GET", null);
            boolean loggedIn = false;
            String username = "";
            if (response.code == 200 && !"null".equals(response.body)) {
                try {
                    JSONObject user = new JSONObject(response.body);
                    username = user.optString("username", "");
                    loggedIn = !username.isEmpty();
                } catch (Exception ignored) {
                    loggedIn = false;
                }
            }
            boolean resultLoggedIn = loggedIn;
            String resultUsername = username;
            mainHandler.post(() -> {
                if (generation != accountGeneration) return;
                signedIn = resultLoggedIn;
                signedInUsername = resultUsername;
                updateAccountButton();
                if (after != null) after.run();
            });
        }, "AdolarAccountStatus").start();
    }

    private void login(
            String username,
            String password,
            TextView accountStatus,
            EditText usernameInput,
            EditText passwordInput,
            Button loginButton,
            Button logoutButton,
            TextView loginError
    ) {
        if (username.trim().isEmpty() || password.isEmpty()) {
            loginError.setText(R.string.login_invalid);
            loginError.setVisibility(View.VISIBLE);
            return;
        }
        loginButton.setEnabled(false);
        loginError.setVisibility(View.GONE);
        accountStatus.setText(R.string.login_working);
        final int generation = ++accountGeneration;
        new Thread(() -> {
            JSONObject body = new JSONObject();
            try {
                body.put("username", username.trim());
                body.put("password", password);
                body.put("remember", true);
            } catch (Exception ignored) {
                // The values above are valid JSON primitives.
            }
            ApiResponse response = requestApi("/api/radio/login", "POST", body);
            String resultUsername = "";
            String errorCode = "";
            if (response.code == 200) {
                try {
                    resultUsername = new JSONObject(response.body).optString("username", "");
                } catch (Exception ignored) {
                    errorCode = "invalid_response";
                }
            } else {
                try {
                    errorCode = new JSONObject(response.body).optString("error", "");
                } catch (Exception ignored) {
                    errorCode = "connection";
                }
            }
            String finalUsername = resultUsername;
            String finalError = errorCode;
            mainHandler.post(() -> {
                if (generation != accountGeneration) return;
                loginButton.setEnabled(true);
                passwordInput.setText("");
                if (response.code == 200 && !finalUsername.isEmpty()) {
                    signedIn = true;
                    signedInUsername = finalUsername;
                    updateAccountButton();
                    updateAccountSettings(
                            accountStatus, usernameInput, passwordInput, loginButton, logoutButton
                    );
                    reloadStationsForAccount();
                    refreshTrackActions();
                } else {
                    signedIn = false;
                    signedInUsername = "";
                    accountStatus.setText(R.string.account_signed_out);
                    loginError.setText(loginErrorMessage(finalError));
                    loginError.setVisibility(View.VISIBLE);
                }
            });
        }, "AdolarLogin").start();
    }

    private void logout(Runnable after) {
        final int generation = ++accountGeneration;
        new Thread(() -> {
            requestApi("/api/radio/logout", "POST", new JSONObject());
            CookieManager cookies = CookieManager.getInstance();
            cookies.setCookie(
                    AdolarPrefs.apiUrl(this), "adolar_session=; Max-Age=0; Path=/"
            );
            cookies.flush();
            mainHandler.post(() -> {
                if (generation != accountGeneration) return;
                signedIn = false;
                signedInUsername = "";
                favorite = false;
                lastFmConnected = false;
                updateAccountButton();
                updateTrackActionButtons();
                reloadStationsForAccount();
                if (after != null) after.run();
            });
        }, "AdolarLogout").start();
    }

    private void updateAccountSettings(
            TextView status,
            EditText username,
            EditText password,
            Button login,
            Button logout
    ) {
        status.setText(signedIn
                ? getString(R.string.account_signed_in, signedInUsername)
                : getString(R.string.account_signed_out));
        int loginVisibility = signedIn ? View.GONE : View.VISIBLE;
        username.setVisibility(loginVisibility);
        password.setVisibility(loginVisibility);
        login.setVisibility(loginVisibility);
        logout.setVisibility(signedIn ? View.VISIBLE : View.GONE);
    }

    private void updateAccountButton() {
        if (accountButton == null) return;
        if (signedIn) {
            accountButton.setText(signedInUsername);
            accountButton.setTypeface(orbitronMedium);
            accountButton.setLetterSpacing(0.04f);
            accountButton.setCompoundDrawablesRelativeWithIntrinsicBounds(0, 0, 0, 0);
            accountButton.setPadding(dp(10), 0, dp(10), 0);
            accountButton.setContentDescription(
                    getString(R.string.account_signed_in, signedInUsername)
            );
        } else {
            accountButton.setText("");
            accountButton.setLetterSpacing(0f);
            accountButton.setCompoundDrawablesRelativeWithIntrinsicBounds(
                    R.drawable.ic_person_outline, 0, 0, 0
            );
            accountButton.setPadding(dp(10), 0, dp(10), 0);
            accountButton.setContentDescription(getString(R.string.login));
        }
    }

    private void reloadStationsForAccount() {
        stations.clear();
        if (mediaBrowser != null && mediaBrowser.isConnected()) {
            subscribeToStations();
        }
    }

    private void refreshTrackActions() {
        final int trackId = currentTrackId;
        final String artist = currentTrackArtist;
        final String title = currentTrackTitle;
        final int generation = ++trackActionGeneration;
        favorite = false;
        lastFmConnected = false;
        updateTrackActionButtons();
        if (!signedIn || trackId < 0) return;
        new Thread(() -> {
            boolean isFavorite = false;
            boolean isConnected = false;
            boolean isLoved = loved;
            ApiResponse favoriteResponse = requestApi(
                    "/api/favorites?ids=" + trackId, "GET", null
            );
            if (favoriteResponse.code == 200) {
                try {
                    JSONArray ids = new JSONObject(favoriteResponse.body).getJSONArray("track_ids");
                    for (int index = 0; index < ids.length(); index++) {
                        if (ids.getInt(index) == trackId) isFavorite = true;
                    }
                } catch (Exception ignored) {
                    isFavorite = false;
                }
            }
            ApiResponse statusResponse = requestApi("/api/lastfm/status", "GET", null);
            if (statusResponse.code == 200) {
                try {
                    isConnected = new JSONObject(statusResponse.body).optBoolean("connected", false);
                } catch (Exception ignored) {
                    isConnected = false;
                }
            }
            if (isConnected && !artist.isEmpty() && !title.isEmpty()) {
                String query = new Uri.Builder()
                        .appendQueryParameter("artist", artist)
                        .appendQueryParameter("title", title)
                        .build().getEncodedQuery();
                ApiResponse lovedResponse = requestApi("/api/lastfm/loved?" + query, "GET", null);
                if (lovedResponse.code == 200) {
                    try {
                        isLoved = new JSONObject(lovedResponse.body).optBoolean("loved", isLoved);
                    } catch (Exception ignored) {
                        // Keep the loved value supplied with the track.
                    }
                }
            }
            boolean resultFavorite = isFavorite;
            boolean resultConnected = isConnected;
            boolean resultLoved = isLoved;
            mainHandler.post(() -> {
                if (generation != trackActionGeneration || trackId != currentTrackId) return;
                favorite = resultFavorite;
                lastFmConnected = resultConnected;
                loved = resultLoved;
                updateTrackActionButtons();
            });
        }, "AdolarTrackActions").start();
    }

    private void toggleFavorite() {
        if (!signedIn) {
            setStatus(getString(R.string.favorite_login_required), true);
            return;
        }
        if (currentTrackId < 0) return;
        final int trackId = currentTrackId;
        final boolean requested = !favorite;
        favoriteButton.setEnabled(false);
        new Thread(() -> {
            JSONObject body = new JSONObject();
            try { body.put("favorite", requested); } catch (Exception ignored) { }
            ApiResponse response = requestApi("/api/favorites/" + trackId, "PUT", body);
            boolean synced = false;
            if (response.code == 200) {
                try {
                    synced = new JSONObject(response.body).optBoolean("lastfm_synced", false);
                } catch (Exception ignored) { }
            }
            boolean lastFmSynced = synced;
            mainHandler.post(() -> {
                if (trackId != currentTrackId) return;
                if (response.code == 200) {
                    favorite = requested;
                    if (lastFmSynced) loved = true;
                } else {
                    setStatus(getString(R.string.track_action_error), true);
                }
                updateTrackActionButtons();
            });
        }, "AdolarFavorite").start();
    }

    private void toggleLove() {
        if (!lastFmConnected || currentTrackArtist.isEmpty() || currentTrackTitle.isEmpty()) {
            setStatus(getString(R.string.lastfm_required), true);
            return;
        }
        final int trackId = currentTrackId;
        final String artist = currentTrackArtist;
        final String title = currentTrackTitle;
        final boolean requested = !loved;
        loveButton.setEnabled(false);
        new Thread(() -> {
            JSONObject body = new JSONObject();
            try {
                body.put("artist", artist);
                body.put("title", title);
                body.put("action", requested ? "love" : "unlove");
            } catch (Exception ignored) { }
            ApiResponse response = requestApi("/api/lastfm/love", "POST", body);
            mainHandler.post(() -> {
                if (trackId != currentTrackId) return;
                if (response.code == 200) {
                    loved = requested;
                } else {
                    setStatus(getString(R.string.track_action_error), true);
                }
                updateTrackActionButtons();
            });
        }, "AdolarLastFmLove").start();
    }

    private void updateTrackActionButtons() {
        if (favoriteButton == null || loveButton == null) return;
        favoriteButton.setText(favorite ? R.string.favorite_on : R.string.favorite_off);
        loveButton.setText(loved ? R.string.love_on : R.string.love_off);
        boolean hasTrack = currentTrackId >= 0;
        favoriteButton.setEnabled(signedIn && hasTrack);
        loveButton.setEnabled(signedIn && lastFmConnected && hasTrack);
        favoriteButton.setAlpha(favoriteButton.isEnabled() ? 1f : 0.45f);
        loveButton.setAlpha(loveButton.isEnabled() ? 1f : 0.45f);
    }

    private int loginErrorMessage(String error) {
        switch (error) {
            case "invalid_credentials": return R.string.login_invalid;
            case "blocked": return R.string.login_blocked;
            case "must_change_password": return R.string.login_password_change;
            case "setup_required": return R.string.login_setup_required;
            default: return R.string.login_error;
        }
    }

    private ApiResponse requestApi(String path, String method, JSONObject body) {
        HttpURLConnection connection = null;
        try {
            String base = AdolarPrefs.apiUrl(this);
            connection = (HttpURLConnection) new URL(base + path).openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(12000);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("X-Adolar-Product", "android");
            String cookie = CookieManager.getInstance().getCookie(base);
            if (cookie != null && !cookie.isEmpty()) {
                connection.setRequestProperty("Cookie", cookie);
            }
            if (body != null) {
                byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setFixedLengthStreamingMode(payload.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(payload);
                }
            }
            int code = connection.getResponseCode();
            for (java.util.Map.Entry<String, List<String>> header
                    : connection.getHeaderFields().entrySet()) {
                if (header.getKey() != null
                        && "Set-Cookie".equalsIgnoreCase(header.getKey())) {
                    for (String value : header.getValue()) {
                        CookieManager.getInstance().setCookie(base, value);
                    }
                }
            }
            CookieManager.getInstance().flush();
            InputStream stream = code >= 200 && code < 400
                    ? connection.getInputStream()
                    : connection.getErrorStream();
            return new ApiResponse(code, readStream(stream));
        } catch (Exception ignored) {
            return new ApiResponse(0, "");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String readStream(InputStream stream) throws Exception {
        if (stream == null) return "";
        StringBuilder result = new StringBuilder();
        byte[] buffer = new byte[4096];
        int count;
        try (InputStream input = stream) {
            while ((count = input.read(buffer)) != -1) {
                result.append(new String(buffer, 0, count, StandardCharsets.UTF_8));
            }
        }
        return result.toString();
    }

    private void showCover(String address) {
        if (coverView == null) {
            return;
        }
        final int generation = ++coverGeneration;
        if (address == null || address.isEmpty()) {
            coverView.setImageResource(R.drawable.ic_launcher_foreground);
            return;
        }
        new Thread(() -> {
            HttpURLConnection connection = null;
            Bitmap bitmap = null;
            try {
                connection = (HttpURLConnection) new URL(address).openConnection();
                connection.setConnectTimeout(8000);
                connection.setReadTimeout(8000);
                try (InputStream stream = connection.getInputStream()) {
                    bitmap = BitmapFactory.decodeStream(stream);
                }
            } catch (Exception ignored) {
                bitmap = null;
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
            Bitmap loaded = bitmap;
            mainHandler.post(() -> {
                if (generation != coverGeneration || coverView == null) {
                    return;
                }
                if (loaded == null) {
                    coverView.setImageResource(R.drawable.ic_launcher_foreground);
                } else {
                    coverView.setImageBitmap(loaded);
                }
            });
        }, "AdolarCoverLoader").start();
    }

    private void setStatus(String message, boolean error) {
        if (playbackStatus == null) {
            return;
        }
        playbackStatus.setText(message);
        playbackStatus.setTextColor(error
                ? Color.rgb(224, 92, 92)
                : getColorCompat(R.color.accent_light));
    }

    private void setControlsEnabled(boolean enabled) {
        if (playPauseButton == null) {
            return;
        }
        playPauseButton.setEnabled(enabled);
        previousButton.setEnabled(enabled);
        nextButton.setEnabled(enabled);
        stopButton.setEnabled(enabled);
    }

    private void updateSelectedStationLabel() {
        if (selectedStationLabel == null) {
            return;
        }
        String name = selectedStation == null ? "–" : selectedStation.name;
        selectedStationLabel.setText(getString(R.string.station_selected_format, name));
    }

    @Override
    public void onBackPressed() {
        if (showingSettings && AdolarPrefs.hasServerUrl(this)) {
            showPlayer();
            return;
        }
        super.onBackPressed();
    }

    private void applySystemBarInsets(View view) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            getWindow().setDecorFitsSystemWindows(false);
        }
        view.setOnApplyWindowInsetsListener((target, insets) -> {
            int left;
            int top;
            int right;
            int bottom;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                left = bars.left;
                top = bars.top;
                right = bars.right;
                bottom = bars.bottom;
            } else {
                left = insets.getSystemWindowInsetLeft();
                top = insets.getSystemWindowInsetTop();
                right = insets.getSystemWindowInsetRight();
                bottom = insets.getSystemWindowInsetBottom();
            }
            target.setPadding(left, top, right, bottom);
            return insets;
        });
        view.requestApplyInsets();
    }

    private TextView label(String text, int size, int colorResource) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(getColorCompat(colorResource));
        view.setTextSize(size);
        return view;
    }

    private Button controlButton(
            String text, boolean primary, boolean destructive, View.OnClickListener listener
    ) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextSize(primary ? 25 : 21);
        button.setAllCaps(false);
        button.setMinWidth(0);
        button.setMinHeight(0);
        button.setPadding(0, 0, 0, 0);
        button.setStateListAnimator(null);
        int foreground = destructive
                ? Color.rgb(224, 92, 92)
                : getColorCompat(R.color.text_primary);
        button.setTextColor(foreground);
        if (primary) {
            button.setBackground(ovalRipple(
                    getColorCompat(R.color.accent_deep),
                    getColorCompat(R.color.accent_light)
            ));
            button.setElevation(dp(5));
        } else {
            button.setBackground(roundedRipple(
                    getColorCompat(R.color.bg_primary),
                    destructive
                            ? Color.rgb(112, 58, 58)
                            : getColorCompat(R.color.border_medium),
                    dp(12),
                    destructive ? Color.rgb(224, 92, 92) : getColorCompat(R.color.accent)
            ));
            button.setElevation(0);
        }
        button.setOnClickListener(listener);
        return button;
    }

    private Button compactHeaderButton(int iconResource) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setTextColor(getColorCompat(R.color.text_secondary));
        button.setTextSize(11);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setMinWidth(0);
        button.setMinHeight(0);
        button.setPadding(dp(10), 0, dp(10), 0);
        button.setCompoundDrawablesRelativeWithIntrinsicBounds(iconResource, 0, 0, 0);
        button.setBackground(roundedRipple(
                getColorCompat(R.color.bg_primary),
                getColorCompat(R.color.border_medium),
                dp(9),
                getColorCompat(R.color.accent)
        ));
        return button;
    }

    private Button trackActionButton(String text, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(13);
        button.setTextColor(getColorCompat(R.color.text_primary));
        button.setMinWidth(0);
        button.setMinHeight(0);
        button.setPadding(dp(8), 0, dp(8), 0);
        button.setBackground(roundedRipple(
                getColorCompat(R.color.bg_primary),
                getColorCompat(R.color.border_medium),
                dp(10),
                getColorCompat(R.color.accent)
        ));
        button.setOnClickListener(listener);
        return button;
    }

    private LinearLayout.LayoutParams controlParams(int size, int margin) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(size), dp(size));
        params.setMargins(dp(margin), 0, dp(margin), 0);
        return params;
    }

    private void stylePrimaryAction(Button button) {
        button.setTextColor(Color.WHITE);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setBackground(roundedRipple(
                getColorCompat(R.color.accent_deep),
                Color.TRANSPARENT,
                dp(9),
                getColorCompat(R.color.accent_light)
        ));
    }

    private void styleSecondaryAction(Button button) {
        button.setTextColor(getColorCompat(R.color.text_primary));
        button.setBackground(roundedRipple(
                getColorCompat(R.color.bg_primary),
                getColorCompat(R.color.border_medium),
                dp(9),
                getColorCompat(R.color.accent)
        ));
    }

    private void styleInput(EditText input) {
        input.setTextColor(getColorCompat(R.color.text_primary));
        input.setHintTextColor(getColorCompat(R.color.text_secondary));
        input.setTextSize(15);
        input.setPadding(dp(12), 0, dp(12), 0);
        input.setBackground(roundedRipple(
                getColorCompat(R.color.bg_primary),
                getColorCompat(R.color.border_subtle),
                dp(9),
                getColorCompat(R.color.accent)
        ));
    }

    private GradientDrawable roundedShape(int fillColor, int strokeColor, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fillColor);
        shape.setCornerRadius(radius);
        if (strokeColor != Color.TRANSPARENT) {
            shape.setStroke(dp(1), strokeColor);
        }
        return shape;
    }

    private RippleDrawable roundedRipple(
            int fillColor, int strokeColor, int radius, int rippleColor
    ) {
        GradientDrawable content = roundedShape(fillColor, strokeColor, radius);
        return new RippleDrawable(
                ColorStateList.valueOf(withAlpha(rippleColor, 90)), content, null
        );
    }

    private RippleDrawable ovalRipple(int fillColor, int rippleColor) {
        GradientDrawable content = new GradientDrawable();
        content.setShape(GradientDrawable.OVAL);
        content.setColor(fillColor);
        return new RippleDrawable(
                ColorStateList.valueOf(withAlpha(rippleColor, 110)), content, null
        );
    }

    private int withAlpha(int color, int alpha) {
        return Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color));
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private LinearLayout.LayoutParams inputParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(6), 0, dp(12));
        params.height = dp(48);
        return params;
    }

    private LinearLayout.LayoutParams buttonParams() {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(0, dp(18), 0, 0);
        params.height = dp(48);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private int getColorCompat(int resourceId) {
        return getResources().getColor(resourceId, getTheme());
    }

    private String valueOrFallback(String value, String fallback) {
        return value == null || value.isEmpty() ? fallback : value;
    }

    private static final class StationItem {
        final int id;
        final String mediaId;
        final String name;
        final Bundle extras;

        StationItem(MediaDescriptionCompat description) {
            mediaId = description.getMediaId();
            name = description.getTitle() == null
                    ? "Adolar Radio"
                    : description.getTitle().toString();
            extras = description.getExtras() == null
                    ? new Bundle()
                    : new Bundle(description.getExtras());
            id = extras.getInt("station_id", parseStationId(mediaId));
        }

        private static int parseStationId(String mediaId) {
            if (mediaId == null || !mediaId.startsWith("station:")) {
                return 1;
            }
            try {
                return Integer.parseInt(mediaId.substring("station:".length()));
            } catch (NumberFormatException ignored) {
                return 1;
            }
        }

        @Override
        public String toString() {
            return name;
        }
    }

    private static final class ApiResponse {
        final int code;
        final String body;

        ApiResponse(int code, String body) {
            this.code = code;
            this.body = body == null ? "" : body;
        }
    }

    private final class StationAdapter extends ArrayAdapter<StationItem> {
        StationAdapter(List<StationItem> values) {
            super(MainActivity.this, android.R.layout.simple_spinner_item, values);
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            TextView view = (TextView) super.getView(position, convertView, parent);
            view.setTextColor(getColorCompat(R.color.text_primary));
            view.setTextSize(16);
            view.setPadding(dp(12), 0, dp(12), 0);
            return view;
        }
    }
}
