package net.polze.adolarradio;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.support.v4.media.MediaBrowserCompat;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaControllerCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;
import android.text.Editable;
import android.text.TextWatcher;

import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.GravityCompat;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.drawerlayout.widget.DrawerLayout;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import net.polze.adolarradio.local.LibraryFacet;
import net.polze.adolarradio.local.ArtworkCache;
import net.polze.adolarradio.local.ArtworkPrefetchWorker;
import net.polze.adolarradio.local.LocalPlaylist;
import net.polze.adolarradio.local.LocalLibraryRepository;
import net.polze.adolarradio.local.LocalLibraryRepository.FacetType;
import net.polze.adolarradio.local.LocalLibraryScanner;
import net.polze.adolarradio.local.LocalTrack;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Offline-first launcher and local-library shell for Adolar Next. */
public class NextActivity extends Activity {
    private static final int REQUEST_MUSIC_TREE = 2001;
    private static final int REQUEST_MEDIA_PERMISSION = 2002;
    private static final String LOCAL_TRACK_PREFIX = "local:";
    private static final int DRAWER_GRAVITY = GravityCompat.START;

    private DrawerLayout drawerLayout;
    private LinearLayout contentContainer;
    private View drawerView;
    private RecyclerView trackList;
    private FrameLayout libraryFrame;
    private View nowPlayingPanel;
    private TrackAdapter adapter;
    private FacetAdapter facetAdapter;
    private PlaylistAdapter playlistAdapter;
    private TextView toolbarIcon;
    private TextView toolbarTitle;
    private TextView toolbarBack;
    private Button toolbarSearch;
    private EditText searchInput;
    private TextView statusView;
    private Button emptyAction;
    private LinearLayout scanPanel;
    private TextView scanPanelText;
    private View miniPlayer;
    private TextView miniTitle;
    private TextView miniArtist;
    private TextView miniPlayPause;
    private ImageView miniArtwork;
    private ImageView playerArtwork;
    private TextView playerTitle;
    private TextView playerArtist;
    private TextView playerAlbum;
    private TextView playerSource;
    private TextView playerElapsed;
    private TextView playerDuration;
    private TextView playerShuffle;
    private TextView playerPlayPause;
    private Button playerLove;
    private SeekBar playerSeek;
    private LocalTrack nowPlayingLocalTrack;
    private long nowPlayingTrackId = -1L;
    private boolean userSeeking;
    private LocalLibraryRepository repository;
    private ArtworkCache artworkCache;
    private MediaBrowserCompat mediaBrowser;
    private MediaControllerCompat mediaController;
    private Long pendingTrackId;
    private Uri pendingScanUri;
    private boolean pendingScanAll;
    private boolean scanning;
    private boolean liveRefreshPending;
    private long lastLiveRefreshAt;
    private final Handler uiHandler = new Handler(Looper.getMainLooper());
    private Runnable pendingSearch;
    private int searchGeneration;
    private Screen screen = Screen.TRACKS;
    private Screen screenBeforeNowPlaying = Screen.TRACKS;
    private FacetType activeFacetType;
    private String activeFacetName;
    private LocalPlaylist activePlaylist;
    private final Set<Long> favoriteTrackIds = new HashSet<>();

    private enum Screen {
        TRACKS, SEARCH, FACETS, FACET_TRACKS, PLAYLISTS, PLAYLIST_TRACKS, NOW_PLAYING
    }

    private final Runnable playerProgress = new Runnable() {
        @Override
        public void run() {
            updatePlayerProgress();
            if (screen == Screen.NOW_PLAYING) uiHandler.postDelayed(this, 500L);
        }
    };

    private final MediaBrowserCompat.ConnectionCallback browserCallback =
            new MediaBrowserCompat.ConnectionCallback() {
                @Override
                public void onConnected() {
                    try {
                        mediaController = new MediaControllerCompat(
                                NextActivity.this, mediaBrowser.getSessionToken()
                        );
                        MediaControllerCompat.setMediaController(NextActivity.this, mediaController);
                        mediaController.registerCallback(controllerCallback);
                        updateMiniPlayer(
                                mediaController.getMetadata(), mediaController.getPlaybackState()
                        );
                        updateShuffleButton(
                                mediaController.getShuffleMode(), mediaController.getMetadata()
                        );
                        if (pendingTrackId != null) {
                            long trackId = pendingTrackId;
                            pendingTrackId = null;
                            playLocalTrack(trackId);
                        }
                    } catch (Exception error) {
                        Toast.makeText(
                                NextActivity.this,
                                R.string.status_connection_error,
                                Toast.LENGTH_SHORT
                        ).show();
                    }
                }

                @Override
                public void onConnectionSuspended() {
                    detachController();
                }

                @Override
                public void onConnectionFailed() {
                    detachController();
                }
            };

    private final MediaControllerCompat.Callback controllerCallback =
            new MediaControllerCompat.Callback() {
                @Override
                public void onMetadataChanged(MediaMetadataCompat metadata) {
                    updateMiniPlayer(metadata, mediaController == null
                            ? null : mediaController.getPlaybackState());
                }

                @Override
                public void onPlaybackStateChanged(PlaybackStateCompat state) {
                    updateMiniPlayer(mediaController == null
                            ? null : mediaController.getMetadata(), state);
                }

                @Override
                public void onShuffleModeChanged(int shuffleMode) {
                    updateShuffleButton(shuffleMode, mediaController == null
                            ? null : mediaController.getMetadata());
                }
            };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        repository = LocalLibraryRepository.get(this);
        artworkCache = ArtworkCache.get(this);
        requestNotificationPermissionIfNeeded();
        buildUi();
        refreshFavoriteIds();
        refreshTracks();
    }

    @Override
    protected void onStart() {
        super.onStart();
        connectBrowser();
    }

    @Override
    protected void onStop() {
        detachController();
        super.onStop();
    }

    private void buildUi() {
        drawerLayout = new DrawerLayout(this);
        drawerLayout.setBackgroundColor(color(R.color.bg_tertiary));

        LinearLayout content = new LinearLayout(this);
        contentContainer = content;
        content.setOrientation(LinearLayout.VERTICAL);
        content.setBackgroundColor(color(R.color.bg_tertiary));
        DrawerLayout.LayoutParams contentParams = new DrawerLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        );
        drawerLayout.addView(content, contentParams);

        content.addView(buildToolbar(), new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(64)
        ));

        searchInput = new EditText(this);
        searchInput.setSingleLine(true);
        searchInput.setHint(R.string.library_search_hint);
        searchInput.setTextColor(color(R.color.text_primary));
        searchInput.setHintTextColor(color(R.color.text_secondary));
        searchInput.setBackgroundColor(color(R.color.bg_secondary));
        searchInput.setPadding(dp(16), 0, dp(16), 0);
        searchInput.setVisibility(View.GONE);
        searchInput.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence value, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence value, int start, int before, int count) {
                scheduleSearch(value.toString());
            }

            @Override
            public void afterTextChanged(Editable value) {
            }
        });
        content.addView(searchInput, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)
        ));

        statusView = text("", 13, R.color.text_secondary);
        statusView.setPadding(dp(16), dp(8), dp(16), dp(8));
        content.addView(statusView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        libraryFrame = new FrameLayout(this);
        LinearLayout.LayoutParams libraryParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        );
        content.addView(libraryFrame, libraryParams);

        trackList = new RecyclerView(this);
        trackList.setLayoutManager(new LinearLayoutManager(this));
        trackList.setHasFixedSize(true);
        trackList.setItemAnimator(null);
        trackList.setBackgroundColor(color(R.color.bg_tertiary));
        adapter = new TrackAdapter(this::playLocalTrack);
        facetAdapter = new FacetAdapter(this::openFacet);
        playlistAdapter = new PlaylistAdapter(this::openPlaylist);
        trackList.setAdapter(adapter);
        libraryFrame.addView(trackList, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ));

        scanPanel = new LinearLayout(this);
        scanPanel.setOrientation(LinearLayout.VERTICAL);
        scanPanel.setGravity(Gravity.CENTER);
        ProgressBar scanProgress = new ProgressBar(this);
        scanProgress.setIndeterminate(true);
        scanPanel.addView(scanProgress, new LinearLayout.LayoutParams(dp(56), dp(56)));
        scanPanelText = text(getString(R.string.library_scan_waiting), 16, R.color.text_primary);
        scanPanelText.setGravity(Gravity.CENTER);
        scanPanelText.setPadding(dp(16), dp(12), dp(16), 0);
        scanPanel.addView(scanPanelText, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        scanPanel.setVisibility(View.GONE);
        FrameLayout.LayoutParams scanParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER
        );
        libraryFrame.addView(scanPanel, scanParams);

        emptyAction = new Button(this);
        emptyAction.setText(R.string.library_choose_folder);
        emptyAction.setAllCaps(false);
        emptyAction.setTextColor(Color.WHITE);
        emptyAction.setBackgroundColor(color(R.color.accent_deep));
        emptyAction.setOnClickListener(view -> chooseMusicFolder());
        FrameLayout.LayoutParams emptyParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(52), Gravity.CENTER
        );
        libraryFrame.addView(emptyAction, emptyParams);

        nowPlayingPanel = buildNowPlayingPanel();
        nowPlayingPanel.setVisibility(View.GONE);
        libraryFrame.addView(nowPlayingPanel, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ));

        miniPlayer = buildMiniPlayer();
        content.addView(miniPlayer, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(72)
        ));

        View drawer = buildDrawer();
        drawerView = drawer;
        DrawerLayout.LayoutParams drawerParams = new DrawerLayout.LayoutParams(
                Math.min(dp(320), getResources().getDisplayMetrics().widthPixels - dp(48)),
                ViewGroup.LayoutParams.MATCH_PARENT
        );
        drawerParams.gravity = DRAWER_GRAVITY;
        drawerLayout.addView(drawer, drawerParams);
        setContentView(drawerLayout);
        applyWindowInsets();
    }

    private void applyWindowInsets() {
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        ViewCompat.setOnApplyWindowInsetsListener(drawerLayout, (view, windowInsets) -> {
            Insets bars = windowInsets.getInsets(
                    WindowInsetsCompat.Type.systemBars()
                            | WindowInsetsCompat.Type.displayCutout()
            );
            Insets keyboard = windowInsets.getInsets(WindowInsetsCompat.Type.ime());
            // DrawerLayout measures its children independently of its own padding.
            // Insets therefore belong on the content child; padding the drawer root
            // pushed the toolbar behind the status bar and the player behind nav/IME.
            contentContainer.setPadding(
                    bars.left,
                    bars.top,
                    bars.right,
                    Math.max(bars.bottom, keyboard.bottom)
            );
            drawerView.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return windowInsets;
        });
        ViewCompat.requestApplyInsets(drawerLayout);
    }

    private View buildToolbar() {
        LinearLayout appBar = new LinearLayout(this);
        appBar.setOrientation(LinearLayout.VERTICAL);
        appBar.setBackgroundColor(color(R.color.bg_primary));

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(8), 0, dp(8), 0);
        toolbar.setBackgroundColor(color(R.color.bg_primary));

        ImageButton rocket = new ImageButton(this);
        rocket.setImageResource(R.drawable.ic_launcher_foreground);
        rocket.setScaleType(ImageButton.ScaleType.CENTER_INSIDE);
        rocket.setBackgroundColor(Color.TRANSPARENT);
        rocket.setContentDescription(getString(R.string.navigation_open));
        rocket.setOnClickListener(view -> drawerLayout.openDrawer(DRAWER_GRAVITY));
        toolbar.addView(rocket, new LinearLayout.LayoutParams(dp(52), dp(52)));

        toolbarBack = text("‹", 36, R.color.text_primary);
        toolbarBack.setGravity(Gravity.CENTER);
        toolbarBack.setVisibility(View.GONE);
        toolbarBack.setContentDescription(getString(R.string.navigate_back));
        toolbarBack.setOnClickListener(view -> onBackPressed());
        toolbar.addView(toolbarBack, new LinearLayout.LayoutParams(dp(42), dp(52)));

        toolbarIcon = text("♫", 26, R.color.accent);
        toolbarIcon.setGravity(Gravity.CENTER);
        toolbar.addView(toolbarIcon, new LinearLayout.LayoutParams(dp(42), dp(52)));

        toolbarTitle = text(getString(R.string.library_tracks), 24, R.color.text_primary);
        toolbarTitle.setTypeface(Typeface.DEFAULT_BOLD);
        toolbarTitle.setSingleLine(true);
        toolbar.addView(toolbarTitle, new LinearLayout.LayoutParams(0, dp(52), 1f));

        toolbarSearch = new Button(this);
        toolbarSearch.setText("⌕");
        toolbarSearch.setTextSize(28);
        toolbarSearch.setTextColor(color(R.color.text_primary));
        toolbarSearch.setBackgroundColor(Color.TRANSPARENT);
        toolbarSearch.setContentDescription(getString(R.string.library_drawer_search));
        toolbarSearch.setOnClickListener(view -> showSearch());
        toolbar.addView(toolbarSearch, new LinearLayout.LayoutParams(dp(52), dp(52)));

        Button overflow = new Button(this);
        overflow.setText("⋮");
        overflow.setTextSize(26);
        overflow.setTextColor(color(R.color.text_primary));
        overflow.setBackgroundColor(Color.TRANSPARENT);
        overflow.setContentDescription(getString(R.string.settings_button));
        overflow.setOnClickListener(this::showOverflow);
        toolbar.addView(overflow, new LinearLayout.LayoutParams(dp(52), dp(52)));
        appBar.addView(toolbar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ));

        View accentLine = new View(this);
        accentLine.setBackgroundColor(color(R.color.accent_deep));
        appBar.addView(accentLine, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(2)
        ));
        return appBar;
    }

    private View buildDrawer() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(color(R.color.bg_primary));
        LinearLayout drawer = new LinearLayout(this);
        drawer.setOrientation(LinearLayout.VERTICAL);
        drawer.setPadding(dp(12), dp(18), dp(12), dp(18));
        scroll.addView(drawer, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        ImageButton rocket = new ImageButton(this);
        rocket.setImageResource(R.drawable.ic_launcher_foreground);
        rocket.setScaleType(ImageButton.ScaleType.CENTER_INSIDE);
        rocket.setBackgroundColor(Color.TRANSPARENT);
        rocket.setOnClickListener(view -> drawerLayout.closeDrawer(DRAWER_GRAVITY));
        header.addView(rocket, new LinearLayout.LayoutParams(dp(62), dp(62)));
        TextView brand = text(getString(R.string.app_name), 23, R.color.accent_light);
        brand.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(brand, new LinearLayout.LayoutParams(0, dp(62), 1f));
        drawer.addView(header, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(70)
        ));

        addDrawerHeading(drawer, "SCHNELLZUGRIFF");
        addSystemDrawerItem(drawer, R.string.library_drawer_favorites, "favorites");
        addSystemDrawerItem(drawer, R.string.library_drawer_recently_added, "recently_added");
        addSystemDrawerItem(drawer, R.string.library_drawer_most_played, "most_played");
        addSystemDrawerItem(
                drawer, R.string.library_drawer_recently_played, "recently_played"
        );
        addSystemDrawerItem(drawer, R.string.library_drawer_least_played, "least_played");
        addSystemDrawerItem(drawer, R.string.library_drawer_never_played, "never_played");

        addDrawerHeading(drawer, "BIBLIOTHEK");
        addDrawerItem(drawer, getString(R.string.library_drawer_search), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showSearch();
        });
        addDrawerItem(drawer, getString(R.string.library_drawer_albums), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showFacets(FacetType.ALBUM);
        });
        addDrawerItem(drawer, getString(R.string.library_drawer_artists), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showFacets(FacetType.ARTIST);
        });
        addDrawerItem(drawer, getString(R.string.library_drawer_genres), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showFacets(FacetType.GENRE);
        });
        addDrawerItem(drawer, getString(R.string.library_drawer_playlists), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showPlaylists();
        });
        addDrawerItem(drawer, getString(R.string.library_drawer_folders), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            chooseMusicFolder();
        });
        addDrawerItem(drawer, getString(R.string.library_tracks), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showAllTracks();
        });
        addDrawerItem(drawer, getString(R.string.library_open_radios), view -> openRadios());
        addPendingDrawerItem(drawer, R.string.library_drawer_sync);
        addDrawerHeading(drawer, "APP");
        addDrawerItem(drawer, getString(R.string.local_settings), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            showLocalSettings();
        });
        return scroll;
    }

    private View buildMiniPlayer() {
        LinearLayout mini = new LinearLayout(this);
        mini.setOrientation(LinearLayout.VERTICAL);
        mini.setBackgroundColor(color(R.color.bg_primary));

        View divider = new View(this);
        divider.setBackgroundColor(color(R.color.accent_deep));
        mini.addView(divider, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(2)
        ));

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        controls.setPadding(dp(8), dp(4), dp(6), dp(4));
        miniArtwork = new ImageView(this);
        showArtworkPlaceholder(miniArtwork);
        controls.addView(miniArtwork, new LinearLayout.LayoutParams(dp(52), dp(52)));
        LinearLayout labels = new LinearLayout(this);
        labels.setOrientation(LinearLayout.VERTICAL);
        labels.setGravity(Gravity.CENTER_VERTICAL);
        miniTitle = text(getString(R.string.library_now_playing_empty), 16, R.color.text_primary);
        miniTitle.setTypeface(Typeface.DEFAULT_BOLD);
        miniTitle.setSingleLine(true);
        miniArtist = text("Adolar Next", 13, R.color.text_secondary);
        miniArtist.setSingleLine(true);
        labels.addView(miniTitle);
        labels.addView(miniArtist);
        labels.setContentDescription(getString(R.string.now_playing_open));
        labels.setOnClickListener(view -> showNowPlaying());
        controls.addView(labels, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        controls.addView(playerButton(
                getString(R.string.previous), R.string.previous_track,
                false, view -> skipPlayback(-1)
        ), new LinearLayout.LayoutParams(dp(44), dp(52)));
        miniPlayPause = playerButton(
                getString(R.string.play), R.string.play, true, view -> togglePlayback()
        );
        controls.addView(miniPlayPause, new LinearLayout.LayoutParams(dp(52), dp(52)));
        controls.addView(playerButton(
                getString(R.string.next), R.string.next_track,
                false, view -> skipPlayback(1)
        ), new LinearLayout.LayoutParams(dp(44), dp(52)));
        mini.addView(controls, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ));
        return mini;
    }

    private View buildNowPlayingPanel() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(color(R.color.bg_tertiary));
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER_HORIZONTAL);
        panel.setPadding(dp(24), dp(16), dp(24), dp(24));
        scroll.addView(panel, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        playerSource = text(getString(R.string.local_source), 13, R.color.accent_light);
        playerSource.setGravity(Gravity.CENTER);
        panel.addView(playerSource, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(32)
        ));

        playerArtwork = new ImageView(this);
        showArtworkPlaceholder(playerArtwork);
        int artworkSize = Math.min(
                dp(280), getResources().getDisplayMetrics().widthPixels - dp(72)
        );
        LinearLayout.LayoutParams artworkParams = new LinearLayout.LayoutParams(
                artworkSize, artworkSize
        );
        artworkParams.setMargins(0, dp(8), 0, dp(18));
        panel.addView(playerArtwork, artworkParams);

        playerTitle = text(getString(R.string.library_now_playing_empty), 24, R.color.text_primary);
        playerTitle.setTypeface(Typeface.DEFAULT_BOLD);
        playerTitle.setGravity(Gravity.CENTER);
        playerTitle.setSingleLine(true);
        panel.addView(playerTitle, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(42)
        ));
        playerArtist = text(getString(R.string.library_unknown_artist), 17, R.color.text_secondary);
        playerArtist.setGravity(Gravity.CENTER);
        playerArtist.setSingleLine(true);
        panel.addView(playerArtist, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(30)
        ));
        playerAlbum = text("", 14, R.color.text_secondary);
        playerAlbum.setGravity(Gravity.CENTER);
        playerAlbum.setSingleLine(true);
        panel.addView(playerAlbum, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(28)
        ));

        playerSeek = new SeekBar(this);
        playerSeek.setMax(1000);
        playerSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (fromUser) {
                    long duration = currentDurationMs();
                    playerElapsed.setText(formatDuration(duration * progress / 1000L / 1000L));
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
                userSeeking = true;
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                long duration = currentDurationMs();
                if (mediaController != null && duration > 0L) {
                    mediaController.getTransportControls().seekTo(
                            duration * seekBar.getProgress() / 1000L
                    );
                }
                userSeeking = false;
            }
        });
        panel.addView(playerSeek, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)
        ));

        LinearLayout times = new LinearLayout(this);
        times.setOrientation(LinearLayout.HORIZONTAL);
        playerElapsed = text("0:00", 12, R.color.text_secondary);
        playerDuration = text("0:00", 12, R.color.text_secondary);
        playerDuration.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        times.addView(playerElapsed, new LinearLayout.LayoutParams(0, dp(24), 1f));
        times.addView(playerDuration, new LinearLayout.LayoutParams(0, dp(24), 1f));
        panel.addView(times, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(24)
        ));

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.HORIZONTAL);
        controls.setGravity(Gravity.CENTER);
        playerShuffle = playerButton(
                getString(R.string.shuffle_symbol), R.string.shuffle_enable,
                false, view -> toggleShuffle()
        );
        controls.addView(playerShuffle, new LinearLayout.LayoutParams(dp(56), dp(64)));
        controls.addView(playerButton(
                getString(R.string.previous), R.string.previous_track,
                false, view -> skipPlayback(-1)
        ), new LinearLayout.LayoutParams(dp(64), dp(64)));
        playerPlayPause = playerButton(
                getString(R.string.play), R.string.play, true, view -> togglePlayback()
        );
        LinearLayout.LayoutParams playParams = new LinearLayout.LayoutParams(dp(72), dp(64));
        playParams.setMargins(dp(12), 0, dp(12), 0);
        controls.addView(playerPlayPause, playParams);
        controls.addView(playerButton(
                getString(R.string.next), R.string.next_track,
                false, view -> skipPlayback(1)
        ), new LinearLayout.LayoutParams(dp(64), dp(64)));
        panel.addView(controls, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(76)
        ));

        playerLove = new Button(this);
        playerLove.setAllCaps(false);
        playerLove.setText(R.string.love_local_off);
        playerLove.setOnClickListener(view -> toggleNowPlayingFavorite());
        panel.addView(playerLove, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)
        ));
        return scroll;
    }

    private TextView playerButton(
            String label,
            int description,
            boolean primary,
            View.OnClickListener listener
    ) {
        TextView button = text(label, 20, R.color.text_primary);
        button.setGravity(Gravity.CENTER);
        button.setBackgroundColor(primary ? color(R.color.accent_deep) : Color.TRANSPARENT);
        button.setContentDescription(getString(description));
        button.setClickable(true);
        button.setFocusable(true);
        button.setOnClickListener(listener);
        return button;
    }

    private void showOverflow(View anchor) {
        PopupMenu menu = new PopupMenu(this, anchor);
        if (screen == Screen.PLAYLISTS) {
            menu.getMenu().add(getString(R.string.playlist_new));
            menu.setOnMenuItemClickListener(item -> {
                showCreatePlaylistChoice();
                return true;
            });
            menu.show();
            return;
        }
        menu.getMenu().add(getString(R.string.library_choose_folder));
        menu.getMenu().add(getString(R.string.library_rescan));
        menu.getMenu().add(getString(R.string.local_settings));
        menu.getMenu().add(getString(R.string.library_open_radios));
        menu.setOnMenuItemClickListener(item -> {
            String title = item.getTitle().toString();
            if (title.equals(getString(R.string.library_choose_folder))) {
                chooseMusicFolder();
            } else if (title.equals(getString(R.string.library_rescan))) {
                scanAll();
            } else if (title.equals(getString(R.string.local_settings))) {
                showLocalSettings();
            } else {
                openRadios();
            }
            return true;
        });
        menu.show();
    }

    private void showLocalSettings() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(24), dp(8), dp(24), 0);
        TextView description = text(
                getString(R.string.artwork_settings_description), 15, R.color.text_primary
        );
        description.setPadding(0, 0, 0, dp(18));
        panel.addView(description, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        TextView status = text(artworkStatusText(), 14, R.color.text_secondary);
        panel.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button prepare = new Button(this);
        prepare.setText(R.string.artwork_prepare);
        prepare.setAllCaps(false);
        prepare.setOnClickListener(view -> {
            ArtworkPrefetchWorker.enqueue(this, false);
            status.setText(getString(R.string.artwork_started));
        });
        LinearLayout.LayoutParams prepareParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)
        );
        prepareParams.setMargins(0, dp(18), 0, dp(8));
        panel.addView(prepare, prepareParams);

        Button retry = new Button(this);
        retry.setText(R.string.artwork_retry);
        retry.setAllCaps(false);
        retry.setOnClickListener(view -> {
            ArtworkPrefetchWorker.enqueue(this, true);
            status.setText(getString(R.string.artwork_started));
        });
        panel.addView(retry, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)
        ));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.artwork_settings_title)
                .setView(panel)
                .setPositiveButton(android.R.string.ok, null)
                .create();
        dialog.show();
    }

    private String artworkStatusText() {
        SharedPreferences preferences = getSharedPreferences(
                ArtworkPrefetchWorker.PREFS, MODE_PRIVATE
        );
        String state = preferences.getString(ArtworkPrefetchWorker.STATUS, "idle");
        int processed = preferences.getInt(ArtworkPrefetchWorker.PROCESSED, 0);
        int total = preferences.getInt(ArtworkPrefetchWorker.TOTAL, 0);
        int found = preferences.getInt(ArtworkPrefetchWorker.FOUND, 0);
        int errors = preferences.getInt(ArtworkPrefetchWorker.ERRORS, 0);
        if ("running".equals(state)) {
            return getString(
                    R.string.artwork_status_running, processed, total, found, errors
            );
        }
        if ("complete".equals(state)) {
            return getString(
                    R.string.artwork_status_complete,
                    processed, found, errors, artworkCache.cachedImageCount()
            );
        }
        if ("paused".equals(state)) {
            return getString(R.string.artwork_status_paused, processed, total);
        }
        return getString(R.string.artwork_status_idle, artworkCache.cachedImageCount());
    }

    private void addDrawerHeading(LinearLayout drawer, String label) {
        TextView heading = text(label, 12, R.color.accent);
        heading.setPadding(dp(12), dp(14), dp(12), dp(4));
        drawer.addView(heading, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));
    }

    private void addPendingDrawerItem(LinearLayout drawer, int label) {
        addDrawerItem(drawer, getString(label), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            Toast.makeText(this, R.string.library_feature_pending, Toast.LENGTH_SHORT).show();
        });
    }

    private void addSystemDrawerItem(LinearLayout drawer, int label, String systemKey) {
        addDrawerItem(drawer, getString(label), view -> {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            openSystemPlaylist(systemKey);
        });
    }

    private void addDrawerItem(LinearLayout drawer, String label, View.OnClickListener listener) {
        Button item = new Button(this);
        item.setText(label);
        item.setTextSize(17);
        item.setTextColor(color(R.color.text_primary));
        item.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        item.setAllCaps(false);
        item.setBackgroundColor(Color.TRANSPARENT);
        item.setOnClickListener(listener);
        drawer.addView(item, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)
        ));
    }

    private void showAllTracks() {
        leaveNowPlayingSurface();
        screen = Screen.TRACKS;
        activeFacetType = null;
        activeFacetName = null;
        activePlaylist = null;
        hideSearchInput();
        toolbarBack.setVisibility(View.GONE);
        toolbarIcon.setText("♫");
        toolbarTitle.setText(R.string.library_tracks);
        setToolbarSearchAction();
        useTrackList();
        refreshTracks();
    }

    private void showSearch() {
        leaveNowPlayingSurface();
        screen = Screen.SEARCH;
        activeFacetType = null;
        activeFacetName = null;
        activePlaylist = null;
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText("⌕");
        toolbarTitle.setText(R.string.library_drawer_search);
        toolbarSearch.setVisibility(View.GONE);
        useTrackList();
        adapter.setTracks(new ArrayList<>());
        emptyAction.setVisibility(View.GONE);
        scanPanel.setVisibility(View.GONE);
        searchInput.setVisibility(View.VISIBLE);
        statusView.setText(R.string.library_search_empty);
        searchInput.requestFocus();
        searchInput.post(() -> {
            InputMethodManager keyboard = (InputMethodManager) getSystemService(
                    INPUT_METHOD_SERVICE
            );
            if (keyboard != null) {
                keyboard.showSoftInput(searchInput, InputMethodManager.SHOW_IMPLICIT);
            }
        });
        if (searchInput.length() > 0) scheduleSearch(searchInput.getText().toString());
    }

    private void scheduleSearch(String rawQuery) {
        if (screen != Screen.SEARCH || searchInput == null) return;
        if (pendingSearch != null) uiHandler.removeCallbacks(pendingSearch);
        String query = rawQuery.trim();
        int generation = ++searchGeneration;
        if (query.isEmpty()) {
            adapter.setTracks(new ArrayList<>());
            statusView.setText(R.string.library_search_empty);
            return;
        }
        pendingSearch = () -> repository.searchTracks(query, tracks -> {
            if (screen != Screen.SEARCH || generation != searchGeneration) return;
            adapter.setTracks(tracks);
            statusView.setText(getString(R.string.library_search_results, tracks.size()));
        });
        uiHandler.postDelayed(pendingSearch, 250L);
    }

    private void showFacets(FacetType type) {
        leaveNowPlayingSurface();
        screen = Screen.FACETS;
        activeFacetType = type;
        activeFacetName = null;
        activePlaylist = null;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText(facetIcon(type));
        toolbarTitle.setText(facetTitle(type));
        setToolbarSearchAction();
        emptyAction.setVisibility(View.GONE);
        scanPanel.setVisibility(View.GONE);
        trackList.setLayoutManager(new GridLayoutManager(this, 2));
        trackList.setAdapter(facetAdapter);
        facetAdapter.setFacets(new ArrayList<>());
        statusView.setText(R.string.library_loading);
        repository.loadFacets(type, facets -> {
            if (screen != Screen.FACETS || activeFacetType != type) return;
            facetAdapter.setFacets(facets);
            statusView.setText(facets.isEmpty()
                    ? getString(R.string.library_no_facets)
                    : getString(R.string.library_facet_count, facets.size()));
        });
    }

    private void openFacet(LibraryFacet facet) {
        leaveNowPlayingSurface();
        FacetType type = activeFacetType;
        if (type == null) return;
        screen = Screen.FACET_TRACKS;
        activeFacetName = facet.name;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText(facetIcon(type));
        toolbarTitle.setText(facet.name);
        setToolbarSearchAction();
        useTrackList();
        adapter.setTracks(new ArrayList<>());
        statusView.setText(R.string.library_loading);
        repository.loadTracksForFacet(type, facet.name, tracks -> {
            if (screen != Screen.FACET_TRACKS || activeFacetType != type) return;
            adapter.setTracks(tracks);
            statusView.setText(getString(R.string.library_facet_tracks, tracks.size()));
        });
    }

    private void showPlaylists() {
        leaveNowPlayingSurface();
        screen = Screen.PLAYLISTS;
        activeFacetType = null;
        activeFacetName = null;
        activePlaylist = null;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText("▤");
        toolbarTitle.setText(R.string.library_drawer_playlists);
        toolbarSearch.setVisibility(View.VISIBLE);
        toolbarSearch.setText("+");
        toolbarSearch.setOnClickListener(view -> showCreatePlaylistChoice());
        emptyAction.setVisibility(View.GONE);
        scanPanel.setVisibility(View.GONE);
        trackList.setLayoutManager(new LinearLayoutManager(this));
        trackList.setAdapter(playlistAdapter);
        playlistAdapter.setPlaylists(new ArrayList<>());
        statusView.setText(R.string.library_loading);
        repository.loadPlaylists(playlists -> {
            if (screen != Screen.PLAYLISTS) return;
            playlistAdapter.setPlaylists(playlists);
            statusView.setText(getString(R.string.library_facet_count, playlists.size()));
        });
    }

    private void openSystemPlaylist(String systemKey) {
        repository.loadPlaylists(playlists -> {
            for (LocalPlaylist playlist : playlists) {
                if (systemKey.equals(playlist.systemKey)) {
                    openPlaylist(playlist);
                    return;
                }
            }
            Toast.makeText(this, R.string.library_no_facets, Toast.LENGTH_SHORT).show();
        });
    }

    private void openPlaylist(LocalPlaylist playlist) {
        leaveNowPlayingSurface();
        screen = Screen.PLAYLIST_TRACKS;
        activePlaylist = playlist;
        activeFacetType = null;
        activeFacetName = null;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText(playlist.isSystem ? "★" : "▤");
        toolbarTitle.setText(playlist.name);
        setToolbarSearchAction();
        useTrackList();
        adapter.setTracks(new ArrayList<>());
        emptyAction.setVisibility(View.GONE);
        scanPanel.setVisibility(View.GONE);
        statusView.setText(R.string.library_loading);
        repository.loadPlaylistTracks(playlist, tracks -> {
            if (screen != Screen.PLAYLIST_TRACKS || activePlaylist != playlist) return;
            adapter.setTracks(tracks);
            statusView.setText(tracks.isEmpty()
                    ? getString(R.string.playlist_empty)
                    : getString(R.string.library_facet_tracks, tracks.size()));
        });
    }

    private void showCreatePlaylistChoice() {
        String[] types = {
                getString(R.string.playlist_standard),
                getString(R.string.playlist_smart)
        };
        new AlertDialog.Builder(this)
                .setTitle(R.string.playlist_new)
                .setItems(types, (dialog, which) -> showCreatePlaylistDialog(which == 1))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void showCreatePlaylistDialog(boolean smart) {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(24), dp(8), dp(24), 0);
        EditText name = new EditText(this);
        name.setHint(R.string.playlist_name_hint);
        form.addView(name, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));
        EditText rule = null;
        if (smart) {
            rule = new EditText(this);
            rule.setHint(R.string.playlist_rule_hint);
            rule.setMinLines(2);
            form.addView(rule, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ));
        }
        EditText finalRule = rule;
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(smart ? R.string.playlist_smart : R.string.playlist_standard)
                .setView(form)
                .setPositiveButton(R.string.playlist_create, null)
                .setNegativeButton(android.R.string.cancel, null)
                .create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> repository.createPlaylist(
                        name.getText().toString(),
                        smart ? finalRule.getText().toString() : null,
                        (success, message) -> {
                            if (!success) {
                                final EditText errorTarget = smart ? finalRule : name;
                                errorTarget.setError(message);
                                return;
                            }
                            dialog.dismiss();
                            Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
                            showPlaylists();
                        }
                )));
        dialog.show();
    }

    private void showAddToPlaylist(LocalTrack track) {
        repository.loadPlaylists(playlists -> {
            List<LocalPlaylist> writable = new ArrayList<>();
            for (LocalPlaylist playlist : playlists) {
                if (!playlist.isSystem && "static".equals(playlist.type)) writable.add(playlist);
            }
            if (writable.isEmpty()) {
                Toast.makeText(this, R.string.playlist_no_static, Toast.LENGTH_LONG).show();
                return;
            }
            String[] names = new String[writable.size()];
            for (int index = 0; index < writable.size(); index++) {
                names[index] = writable.get(index).name;
            }
            new AlertDialog.Builder(this)
                    .setTitle(R.string.playlist_add_track)
                    .setItems(names, (dialog, which) -> repository.addTrackToPlaylist(
                            writable.get(which).id,
                            track.id,
                            (success, message) -> Toast.makeText(
                                    this, message, Toast.LENGTH_SHORT
                            ).show()
                    ))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    private void showTrackActions(LocalTrack track) {
        boolean favorite = favoriteTrackIds.contains(track.id);
        String[] actions = {
                favorite ? "Nicht mehr lieben" : "Lieben",
                getString(R.string.queue_play_next),
                getString(R.string.queue_add),
                getString(R.string.playlist_add_track)
        };
        new AlertDialog.Builder(this)
                .setTitle(track.title)
                .setItems(actions, (dialog, which) -> {
                    if (which == 0) {
                        repository.setFavorite(track.id, !favorite, (success, message) -> {
                            if (!success) return;
                            if (favorite) favoriteTrackIds.remove(track.id);
                            else favoriteTrackIds.add(track.id);
                            adapter.notifyDataSetChanged();
                            Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
                            if (screen == Screen.PLAYLIST_TRACKS && activePlaylist != null
                                    && "favorites".equals(activePlaylist.systemKey)) {
                                openPlaylist(activePlaylist);
                            }
                        });
                    } else if (which == 1) {
                        addTrackToPlaybackQueue(track, true);
                    } else if (which == 2) {
                        addTrackToPlaybackQueue(track, false);
                    } else {
                        showAddToPlaylist(track);
                    }
                })
                .show();
    }

    private void addTrackToPlaybackQueue(LocalTrack track, boolean playNext) {
        MediaMetadataCompat metadata = mediaController == null
                ? null : mediaController.getMetadata();
        String mediaId = metadata == null ? null
                : metadata.getString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID);
        if (mediaController == null || mediaId == null
                || !mediaId.startsWith(LOCAL_TRACK_PREFIX)) {
            playLocalTrack(track.id);
            Toast.makeText(this, R.string.queue_started, Toast.LENGTH_SHORT).show();
            return;
        }
        Bundle extras = new Bundle();
        extras.putLong(AdolarMediaService.EXTRA_LOCAL_TRACK_ID, track.id);
        mediaController.getTransportControls().sendCustomAction(
                playNext ? AdolarMediaService.ACTION_LOCAL_PLAY_NEXT
                        : AdolarMediaService.ACTION_LOCAL_ADD_TO_QUEUE,
                extras
        );
        Toast.makeText(
                this, playNext ? R.string.queue_next_added : R.string.queue_added,
                Toast.LENGTH_SHORT
        ).show();
    }

    private void refreshFavoriteIds() {
        repository.loadFavoriteIds(ids -> {
            favoriteTrackIds.clear();
            favoriteTrackIds.addAll(ids);
            adapter.notifyDataSetChanged();
        });
    }

    private void useTrackList() {
        trackList.setLayoutManager(new LinearLayoutManager(this));
        trackList.setAdapter(adapter);
    }

    private void setToolbarSearchAction() {
        toolbarSearch.setVisibility(View.VISIBLE);
        toolbarSearch.setText("⌕");
        toolbarSearch.setOnClickListener(view -> showSearch());
    }

    private void hideSearchInput() {
        if (searchInput == null) return;
        searchInput.setVisibility(View.GONE);
        searchInput.clearFocus();
        InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(searchInput.getWindowToken(), 0);
    }

    private int facetTitle(FacetType type) {
        if (type == FacetType.ALBUM) return R.string.library_drawer_albums;
        if (type == FacetType.ARTIST) return R.string.library_drawer_artists;
        return R.string.library_drawer_genres;
    }

    private String facetIcon(FacetType type) {
        if (type == FacetType.ALBUM) return "◉";
        if (type == FacetType.ARTIST) return "♬";
        return "♪";
    }

    private void chooseMusicFolder() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        startActivityForResult(intent, REQUEST_MUSIC_TREE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_MUSIC_TREE || resultCode != RESULT_OK
                || data == null || data.getData() == null) {
            return;
        }
        Uri treeUri = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(
                    treeUri, Intent.FLAG_GRANT_READ_URI_PERMISSION
            );
        } catch (SecurityException error) {
            Toast.makeText(this, R.string.library_scan_failed, Toast.LENGTH_LONG).show();
            return;
        }
        requestFastScanPermissionThenScan(treeUri, false);
    }

    private void requestFastScanPermissionThenScan(Uri treeUri, boolean allRoots) {
        String permission = null;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permission = Manifest.permission.READ_MEDIA_AUDIO;
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            permission = Manifest.permission.READ_EXTERNAL_STORAGE;
        }
        if (permission != null && ContextCompat.checkSelfPermission(this, permission)
                != PackageManager.PERMISSION_GRANTED) {
            pendingScanUri = treeUri;
            pendingScanAll = allRoots;
            requestPermissions(new String[]{permission}, REQUEST_MEDIA_PERMISSION);
            return;
        }
        if (allRoots) {
            scanAllNow();
        } else {
            scanRoot(treeUri);
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_MEDIA_PERMISSION) return;
        Uri scanUri = pendingScanUri;
        boolean allRoots = pendingScanAll;
        pendingScanUri = null;
        pendingScanAll = false;
        // A refusal only disables the MediaStore acceleration. The persisted
        // folder grant still permits the complete, slower SAF scan.
        if (allRoots) {
            scanAllNow();
        } else if (scanUri != null) {
            scanRoot(scanUri);
        }
    }

    private void scanRoot(Uri treeUri) {
        if (scanning) return;
        beginScan();
        repository.scanRoot(treeUri, scanCallback());
    }

    private void scanAll() {
        requestFastScanPermissionThenScan(null, true);
    }

    private void scanAllNow() {
        if (scanning) return;
        beginScan();
        repository.scanAll(scanCallback());
    }

    private void beginScan() {
        scanning = true;
        liveRefreshPending = false;
        lastLiveRefreshAt = 0L;
        emptyAction.setVisibility(View.GONE);
        scanPanelText.setText(R.string.library_scan_waiting);
        RecyclerView.Adapter<?> visibleAdapter = trackList.getAdapter();
        boolean visibleListEmpty = visibleAdapter == null || visibleAdapter.getItemCount() == 0;
        scanPanel.setVisibility(visibleListEmpty ? View.VISIBLE : View.GONE);
        statusView.setText(R.string.library_scanning);
    }

    private LocalLibraryRepository.ScanCallback scanCallback() {
        return new LocalLibraryRepository.ScanCallback() {
            @Override
            public void onProgress(LocalLibraryScanner.ScanProgress progress) {
                statusView.setText(getString(
                        R.string.library_scan_progress,
                        progress.visited, progress.indexed, progress.errors
                ));
                scanPanelText.setText(getString(
                        R.string.library_scan_found, progress.visited
                ));
                refreshTrackPreviewDuringScan();
            }

            @Override
            public void onComplete(LocalLibraryScanner.ScanProgress progress) {
                scanning = false;
                scanPanel.setVisibility(View.GONE);
                refreshCurrentScreen();
                if (progress.errors > 0) {
                    Toast.makeText(
                            NextActivity.this,
                            R.string.library_scan_failed,
                            Toast.LENGTH_LONG
                    ).show();
                }
            }
        };
    }

    private void refreshTrackPreviewDuringScan() {
        if (screen != Screen.TRACKS) return;
        long now = System.currentTimeMillis();
        if (liveRefreshPending || now - lastLiveRefreshAt < 750L) return;
        liveRefreshPending = true;
        lastLiveRefreshAt = now;
        repository.loadTrackPreview(tracks -> {
            liveRefreshPending = false;
            showTracks(tracks);
        });
    }

    private void refreshTracks() {
        repository.loadTracks(this::showTracks);
    }

    private void refreshCurrentScreen() {
        if (screen == Screen.FACETS && activeFacetType != null) {
            showFacets(activeFacetType);
        } else if (screen == Screen.FACET_TRACKS
                && activeFacetType != null && activeFacetName != null) {
            repository.loadTracksForFacet(activeFacetType, activeFacetName, tracks -> {
                if (screen != Screen.FACET_TRACKS) return;
                adapter.setTracks(tracks);
                statusView.setText(getString(R.string.library_facet_tracks, tracks.size()));
            });
        } else if (screen == Screen.SEARCH) {
            scheduleSearch(searchInput.getText().toString());
        } else if (screen == Screen.PLAYLISTS) {
            showPlaylists();
        } else if (screen == Screen.PLAYLIST_TRACKS && activePlaylist != null) {
            openPlaylist(activePlaylist);
        } else {
            refreshTracks();
        }
    }

    private void showTracks(List<LocalTrack> tracks) {
        if (screen != Screen.TRACKS) return;
        useTrackList();
        adapter.setTracks(tracks);
        boolean empty = tracks.isEmpty();
        emptyAction.setVisibility(empty && !scanning ? View.VISIBLE : View.GONE);
        scanPanel.setVisibility(scanning && empty ? View.VISIBLE : View.GONE);
        if (!scanning) {
            statusView.setText(empty
                    ? getString(R.string.library_empty)
                    : getString(R.string.library_scan_complete, tracks.size()));
        }
    }

    private void connectBrowser() {
        if (mediaBrowser != null && mediaBrowser.isConnected()) return;
        mediaBrowser = new MediaBrowserCompat(
                this,
                new ComponentName(this, AdolarMediaService.class),
                browserCallback,
                null
        );
        mediaBrowser.connect();
    }

    private void detachController() {
        if (mediaController != null) {
            mediaController.unregisterCallback(controllerCallback);
            mediaController = null;
        }
        MediaControllerCompat.setMediaController(this, null);
        if (mediaBrowser != null) {
            mediaBrowser.disconnect();
            mediaBrowser = null;
        }
    }

    private void playLocalTrack(long trackId) {
        if (mediaController == null) {
            pendingTrackId = trackId;
            connectBrowser();
            return;
        }
        Bundle extras = new Bundle();
        extras.putLongArray(AdolarMediaService.EXTRA_LOCAL_QUEUE_IDS, adapter.queueIds());
        extras.putInt(
                AdolarMediaService.EXTRA_LOCAL_QUEUE_INDEX, adapter.indexOfTrack(trackId)
        );
        extras.putString(AdolarMediaService.EXTRA_LOCAL_QUEUE_NAME, currentQueueName());
        mediaController.getTransportControls().playFromMediaId(
                LOCAL_TRACK_PREFIX + trackId, extras
        );
    }

    private void togglePlayback() {
        if (mediaController == null) return;
        PlaybackStateCompat state = mediaController.getPlaybackState();
        if (state != null && state.getState() == PlaybackStateCompat.STATE_PLAYING) {
            mediaController.getTransportControls().pause();
        } else {
            mediaController.getTransportControls().play();
        }
    }

    private void skipPlayback(int direction) {
        if (mediaController == null) return;
        if (direction < 0) {
            mediaController.getTransportControls().skipToPrevious();
        } else {
            mediaController.getTransportControls().skipToNext();
        }
    }

    private void toggleShuffle() {
        if (mediaController == null || playerShuffle == null || !playerShuffle.isEnabled()) return;
        int current = mediaController.getShuffleMode();
        int next = current == PlaybackStateCompat.SHUFFLE_MODE_ALL
                ? PlaybackStateCompat.SHUFFLE_MODE_NONE
                : PlaybackStateCompat.SHUFFLE_MODE_ALL;
        mediaController.getTransportControls().setShuffleMode(next);
        updateShuffleButton(next, mediaController.getMetadata());
    }

    private void updateShuffleButton(int shuffleMode, MediaMetadataCompat metadata) {
        if (playerShuffle == null) return;
        String mediaId = metadata == null ? null
                : metadata.getString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID);
        boolean localTrack = mediaId != null && mediaId.startsWith(LOCAL_TRACK_PREFIX);
        boolean enabled = localTrack && shuffleMode == PlaybackStateCompat.SHUFFLE_MODE_ALL;
        playerShuffle.setEnabled(localTrack);
        playerShuffle.setAlpha(localTrack ? 1f : 0.35f);
        playerShuffle.setBackgroundColor(enabled ? color(R.color.accent_deep) : Color.TRANSPARENT);
        playerShuffle.setContentDescription(getString(
                enabled ? R.string.shuffle_disable : R.string.shuffle_enable
        ));
    }

    private String currentQueueName() {
        if (screen == Screen.PLAYLIST_TRACKS && activePlaylist != null) {
            return activePlaylist.name;
        }
        if (screen == Screen.FACET_TRACKS && activeFacetName != null) {
            return activeFacetName;
        }
        if (screen == Screen.SEARCH) return getString(R.string.library_drawer_search);
        return getString(R.string.library_tracks);
    }

    private void showNowPlaying() {
        if (screen != Screen.NOW_PLAYING) screenBeforeNowPlaying = screen;
        screen = Screen.NOW_PLAYING;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText("▶");
        toolbarTitle.setText(R.string.now_playing_title);
        toolbarSearch.setVisibility(View.GONE);
        statusView.setVisibility(View.GONE);
        miniPlayer.setVisibility(View.GONE);
        trackList.setVisibility(View.GONE);
        emptyAction.setVisibility(View.GONE);
        scanPanel.setVisibility(View.GONE);
        nowPlayingPanel.setVisibility(View.VISIBLE);
        updateNowPlaying(
                mediaController == null ? null : mediaController.getMetadata(),
                mediaController == null ? null : mediaController.getPlaybackState()
        );
        uiHandler.removeCallbacks(playerProgress);
        uiHandler.post(playerProgress);
    }

    private void leaveNowPlayingSurface() {
        if (nowPlayingPanel != null) nowPlayingPanel.setVisibility(View.GONE);
        if (trackList != null) trackList.setVisibility(View.VISIBLE);
        if (statusView != null) statusView.setVisibility(View.VISIBLE);
        if (miniPlayer != null) miniPlayer.setVisibility(View.VISIBLE);
        uiHandler.removeCallbacks(playerProgress);
        userSeeking = false;
    }

    private void returnFromNowPlaying() {
        Screen previous = screenBeforeNowPlaying;
        if (previous == Screen.FACETS && activeFacetType != null) {
            showFacets(activeFacetType);
        } else if (previous == Screen.FACET_TRACKS
                && activeFacetType != null && activeFacetName != null) {
            restoreFacetTracks();
        } else if (previous == Screen.PLAYLISTS) {
            showPlaylists();
        } else if (previous == Screen.PLAYLIST_TRACKS && activePlaylist != null) {
            openPlaylist(activePlaylist);
        } else if (previous == Screen.SEARCH) {
            showSearch();
        } else {
            showAllTracks();
        }
    }

    private void restoreFacetTracks() {
        leaveNowPlayingSurface();
        screen = Screen.FACET_TRACKS;
        hideSearchInput();
        toolbarBack.setVisibility(View.VISIBLE);
        toolbarIcon.setText(facetIcon(activeFacetType));
        toolbarTitle.setText(activeFacetName);
        setToolbarSearchAction();
        useTrackList();
        statusView.setText(R.string.library_loading);
        repository.loadTracksForFacet(activeFacetType, activeFacetName, tracks -> {
            if (screen != Screen.FACET_TRACKS) return;
            adapter.setTracks(tracks);
            statusView.setText(getString(R.string.library_facet_tracks, tracks.size()));
        });
    }

    private void updateNowPlaying(
            MediaMetadataCompat metadata, PlaybackStateCompat playbackState
    ) {
        if (playerTitle == null) return;
        boolean playing = playbackState != null
                && playbackState.getState() == PlaybackStateCompat.STATE_PLAYING;
        playerPlayPause.setText(playing ? R.string.pause : R.string.play);
        playerPlayPause.setContentDescription(getString(playing ? R.string.pause : R.string.play));
        if (metadata == null || metadata.getDescription().getTitle() == null) {
            playerTitle.setText(R.string.library_now_playing_empty);
            playerArtist.setText(R.string.library_unknown_artist);
            playerAlbum.setText("");
            playerSource.setText(getString(
                    R.string.player_source_format, getString(R.string.local_source)
            ));
            playerLove.setEnabled(false);
            nowPlayingLocalTrack = null;
            nowPlayingTrackId = -1L;
            playerArtwork.setTag(null);
            showArtworkPlaceholder(playerArtwork);
            updateShuffleButton(PlaybackStateCompat.SHUFFLE_MODE_NONE, null);
            return;
        }
        playerTitle.setText(metadata.getString(MediaMetadataCompat.METADATA_KEY_TITLE));
        playerArtist.setText(metadata.getString(MediaMetadataCompat.METADATA_KEY_ARTIST));
        playerAlbum.setText(metadata.getString(MediaMetadataCompat.METADATA_KEY_ALBUM));
        String source = metadata.getString(MediaMetadataCompat.METADATA_KEY_DISPLAY_SUBTITLE);
        String sourceName = source == null || source.isEmpty()
                ? getString(R.string.local_source) : source;
        playerSource.setText(getString(R.string.player_source_format, sourceName));
        playerDuration.setText(formatDuration(currentDurationMs() / 1000L));

        String mediaId = metadata.getString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID);
        updateShuffleButton(
                mediaController == null ? PlaybackStateCompat.SHUFFLE_MODE_NONE
                        : mediaController.getShuffleMode(),
                metadata
        );
        if (mediaId != null && mediaId.startsWith(LOCAL_TRACK_PREFIX)) {
            try {
                long trackId = Long.parseLong(mediaId.substring(LOCAL_TRACK_PREFIX.length()));
                bindNowPlayingTrack(trackId);
            } catch (NumberFormatException ignored) {
                playerLove.setEnabled(false);
            }
        } else {
            nowPlayingLocalTrack = null;
            nowPlayingTrackId = -1L;
            playerLove.setEnabled(false);
            playerArtwork.setTag(null);
            showArtworkPlaceholder(playerArtwork);
        }
    }

    private void bindNowPlayingTrack(long trackId) {
        if (nowPlayingTrackId == trackId && nowPlayingLocalTrack != null) {
            updatePlayerLove();
            return;
        }
        nowPlayingTrackId = trackId;
        nowPlayingLocalTrack = null;
        playerLove.setEnabled(false);
        playerArtwork.setTag(null);
        showArtworkPlaceholder(playerArtwork);
        repository.loadTrack(trackId, tracks -> {
            if (nowPlayingTrackId != trackId || tracks.isEmpty()) return;
            nowPlayingLocalTrack = tracks.get(0);
            loadArtwork(playerArtwork, nowPlayingLocalTrack);
            updatePlayerLove();
        });
    }

    private void updatePlayerLove() {
        if (playerLove == null || nowPlayingLocalTrack == null) return;
        boolean favorite = favoriteTrackIds.contains(nowPlayingLocalTrack.id);
        playerLove.setEnabled(true);
        playerLove.setText(favorite ? R.string.love_local_on : R.string.love_local_off);
    }

    private void toggleNowPlayingFavorite() {
        LocalTrack track = nowPlayingLocalTrack;
        if (track == null) return;
        boolean favorite = favoriteTrackIds.contains(track.id);
        repository.setFavorite(track.id, !favorite, (success, message) -> {
            if (!success) return;
            if (favorite) favoriteTrackIds.remove(track.id);
            else favoriteTrackIds.add(track.id);
            adapter.notifyDataSetChanged();
            updatePlayerLove();
            Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
        });
    }

    private long currentDurationMs() {
        MediaMetadataCompat metadata = mediaController == null
                ? null : mediaController.getMetadata();
        return metadata == null ? 0L
                : Math.max(0L, metadata.getLong(MediaMetadataCompat.METADATA_KEY_DURATION));
    }

    private void updatePlayerProgress() {
        if (playerSeek == null || userSeeking || mediaController == null) return;
        PlaybackStateCompat state = mediaController.getPlaybackState();
        long duration = currentDurationMs();
        long position = state == null ? 0L : Math.max(0L, state.getPosition());
        if (state != null && state.getState() == PlaybackStateCompat.STATE_PLAYING) {
            position += Math.max(0L,
                    SystemClock.elapsedRealtime() - state.getLastPositionUpdateTime());
        }
        if (duration > 0L) position = Math.min(position, duration);
        playerSeek.setProgress(duration <= 0L ? 0 : (int) (position * 1000L / duration));
        playerElapsed.setText(formatDuration(position / 1000L));
        playerDuration.setText(formatDuration(duration / 1000L));
    }

    private void updateMiniPlayer(
            MediaMetadataCompat metadata, PlaybackStateCompat playbackState
    ) {
        if (miniTitle == null) return;
        if (metadata == null || metadata.getDescription().getTitle() == null) {
            miniTitle.setText(R.string.library_now_playing_empty);
            miniArtist.setText(R.string.app_name);
            miniArtwork.setTag(null);
            showArtworkPlaceholder(miniArtwork);
        } else {
            miniTitle.setText(metadata.getDescription().getTitle());
            CharSequence artist = metadata.getDescription().getSubtitle();
            miniArtist.setText(artist == null || artist.length() == 0
                    ? getString(R.string.library_unknown_artist) : artist);
            String mediaId = metadata.getString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID);
            if (mediaId != null && mediaId.startsWith(LOCAL_TRACK_PREFIX)) {
                try {
                    LocalTrack local = adapter.findTrack(Long.parseLong(
                            mediaId.substring(LOCAL_TRACK_PREFIX.length())
                    ));
                    if (local != null) {
                        loadArtwork(miniArtwork, local);
                    } else {
                        miniArtwork.setTag(null);
                        showArtworkPlaceholder(miniArtwork);
                        repository.loadTrack(
                                Long.parseLong(mediaId.substring(LOCAL_TRACK_PREFIX.length())),
                                tracks -> {
                                    MediaMetadataCompat current = mediaController == null
                                            ? null : mediaController.getMetadata();
                                    String currentId = current == null ? null : current.getString(
                                            MediaMetadataCompat.METADATA_KEY_MEDIA_ID
                                    );
                                    if (mediaId.equals(currentId) && !tracks.isEmpty()) {
                                        loadArtwork(miniArtwork, tracks.get(0));
                                    }
                                }
                        );
                    }
                } catch (NumberFormatException ignored) {
                    showArtworkPlaceholder(miniArtwork);
                }
            } else {
                miniArtwork.setTag(null);
                showArtworkPlaceholder(miniArtwork);
            }
        }
        boolean playing = playbackState != null
                && playbackState.getState() == PlaybackStateCompat.STATE_PLAYING;
        miniPlayPause.setText(playing ? R.string.pause : R.string.play);
        miniPlayPause.setContentDescription(getString(playing ? R.string.pause : R.string.play));
        updateNowPlaying(metadata, playbackState);
    }

    private void openRadios() {
        drawerLayout.closeDrawer(DRAWER_GRAVITY);
        startActivity(new Intent(this, MainActivity.class));
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    @Override
    public void onBackPressed() {
        if (drawerLayout != null && drawerLayout.isDrawerOpen(DRAWER_GRAVITY)) {
            drawerLayout.closeDrawer(DRAWER_GRAVITY);
            return;
        }
        if (screen == Screen.NOW_PLAYING) {
            returnFromNowPlaying();
            return;
        }
        if (screen == Screen.FACET_TRACKS && activeFacetType != null) {
            showFacets(activeFacetType);
            return;
        }
        if (screen == Screen.PLAYLIST_TRACKS) {
            showPlaylists();
            return;
        }
        if (screen != Screen.TRACKS) {
            showAllTracks();
            return;
        }
        super.onBackPressed();
    }

    private TextView text(String value, int size, int colorResource) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color(colorResource));
        view.setGravity(Gravity.CENTER_VERTICAL);
        return view;
    }

    private void showArtworkPlaceholder(ImageView view) {
        view.setScaleType(ImageView.ScaleType.CENTER);
        view.setBackgroundColor(color(R.color.bg_primary));
        view.setImageResource(R.drawable.ic_music_note);
    }

    private void loadArtwork(ImageView view, LocalTrack track) {
        String key = artworkCache.keyFor(track);
        view.setTag(key);
        showArtworkPlaceholder(view);
        if (track.documentUri == null || track.documentUri.isEmpty()) return;
        artworkCache.load(track, (loadedKey, bitmap) -> {
            if (!loadedKey.equals(view.getTag()) || bitmap == null) return;
            view.setScaleType(ImageView.ScaleType.CENTER_CROP);
            view.setImageBitmap(bitmap);
        });
    }

    private int color(int resource) {
        return getResources().getColor(resource, getTheme());
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static String formatDuration(long totalSeconds) {
        long minutes = totalSeconds / 60;
        long seconds = totalSeconds % 60;
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
    }

    private final class TrackAdapter extends RecyclerView.Adapter<TrackViewHolder> {
        private final List<LocalTrack> tracks = new ArrayList<>();
        private final TrackClickListener clickListener;

        TrackAdapter(TrackClickListener clickListener) {
            this.clickListener = clickListener;
        }

        void setTracks(List<LocalTrack> values) {
            tracks.clear();
            tracks.addAll(values);
            notifyDataSetChanged();
        }

        Long adjacentTrackId(long currentId, int direction) {
            if (tracks.isEmpty()) return null;
            int currentIndex = -1;
            for (int index = 0; index < tracks.size(); index++) {
                if (tracks.get(index).id == currentId) {
                    currentIndex = index;
                    break;
                }
            }
            if (currentIndex < 0) return tracks.get(direction < 0
                    ? tracks.size() - 1 : 0).id;
            int nextIndex = (currentIndex + (direction < 0 ? -1 : 1) + tracks.size())
                    % tracks.size();
            return tracks.get(nextIndex).id;
        }

        long[] queueIds() {
            long[] result = new long[tracks.size()];
            for (int index = 0; index < tracks.size(); index++) {
                result[index] = tracks.get(index).id;
            }
            return result;
        }

        int indexOfTrack(long trackId) {
            for (int index = 0; index < tracks.size(); index++) {
                if (tracks.get(index).id == trackId) return index;
            }
            return -1;
        }

        @Override
        public TrackViewHolder onCreateViewHolder(ViewGroup parent, int viewType) {
            LinearLayout row = new LinearLayout(NextActivity.this);
            row.setOrientation(LinearLayout.VERTICAL);
            row.setBackgroundColor(color(R.color.bg_tertiary));
            row.setLayoutParams(new RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(73)
            ));

            LinearLayout content = new LinearLayout(NextActivity.this);
            content.setOrientation(LinearLayout.HORIZONTAL);
            content.setGravity(Gravity.CENTER_VERTICAL);
            content.setPadding(dp(12), dp(7), dp(4), dp(7));

            ImageView artwork = new ImageView(NextActivity.this);
            showArtworkPlaceholder(artwork);
            content.addView(artwork, new LinearLayout.LayoutParams(dp(48), dp(48)));

            LinearLayout labels = new LinearLayout(NextActivity.this);
            labels.setOrientation(LinearLayout.VERTICAL);
            labels.setGravity(Gravity.CENTER_VERTICAL);
            labels.setPadding(dp(12), 0, dp(8), 0);
            TextView title = text("", 16, R.color.text_primary);
            title.setTypeface(Typeface.DEFAULT_BOLD);
            title.setSingleLine(true);
            TextView artist = text("", 13, R.color.text_secondary);
            artist.setSingleLine(true);
            labels.addView(title);
            labels.addView(artist);
            content.addView(labels, new LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.MATCH_PARENT, 1f));

            TextView duration = text("", 13, R.color.text_secondary);
            duration.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
            content.addView(duration, new LinearLayout.LayoutParams(dp(48),
                    ViewGroup.LayoutParams.MATCH_PARENT));

            Button actions = new Button(NextActivity.this);
            actions.setText("⋮");
            actions.setTextSize(22);
            actions.setTextColor(color(R.color.text_secondary));
            actions.setBackgroundColor(Color.TRANSPARENT);
            actions.setMinWidth(0);
            actions.setMinHeight(0);
            actions.setPadding(0, 0, 0, 0);
            actions.setContentDescription(getString(R.string.track_actions));
            content.addView(actions, new LinearLayout.LayoutParams(dp(44),
                    ViewGroup.LayoutParams.MATCH_PARENT));

            row.addView(content, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            ));
            View divider = new View(NextActivity.this);
            divider.setBackgroundColor(color(R.color.border_subtle));
            LinearLayout.LayoutParams dividerParams = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(1)
            );
            dividerParams.setMargins(dp(72), 0, 0, 0);
            row.addView(divider, dividerParams);
            return new TrackViewHolder(row, artwork, title, artist, duration, actions);
        }

        @Override
        public void onBindViewHolder(TrackViewHolder holder, int position) {
            LocalTrack track = tracks.get(position);
            holder.title.setText(favoriteTrackIds.contains(track.id)
                    ? "★ " + track.title : track.title);
            holder.artist.setText(track.artist);
            holder.duration.setText(formatDuration(track.durationSeconds));
            loadArtwork(holder.artwork, track);
            holder.itemView.setOnClickListener(view -> clickListener.onClick(track.id));
            holder.itemView.setOnLongClickListener(view -> {
                showTrackActions(track);
                return true;
            });
            holder.actions.setOnClickListener(view -> showTrackActions(track));
        }

        @Override
        public int getItemCount() {
            return tracks.size();
        }

        LocalTrack findTrack(long trackId) {
            for (LocalTrack track : tracks) if (track.id == trackId) return track;
            return null;
        }

        @Override
        public void onViewRecycled(TrackViewHolder holder) {
            holder.artwork.setTag(null);
            showArtworkPlaceholder(holder.artwork);
        }
    }

    private final class FacetAdapter extends RecyclerView.Adapter<FacetViewHolder> {
        private final List<LibraryFacet> facets = new ArrayList<>();
        private final FacetClickListener clickListener;

        FacetAdapter(FacetClickListener clickListener) {
            this.clickListener = clickListener;
        }

        void setFacets(List<LibraryFacet> values) {
            facets.clear();
            facets.addAll(values);
            notifyDataSetChanged();
        }

        @Override
        public FacetViewHolder onCreateViewHolder(ViewGroup parent, int viewType) {
            LinearLayout card = new LinearLayout(NextActivity.this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(12), dp(12), dp(12), dp(10));
            card.setBackgroundColor(color(R.color.bg_secondary));
            RecyclerView.LayoutParams cardParams = new RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(184)
            );
            cardParams.setMargins(dp(4), dp(4), dp(4), dp(4));
            card.setLayoutParams(cardParams);

            ImageView artwork = new ImageView(NextActivity.this);
            showArtworkPlaceholder(artwork);
            card.addView(artwork, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            ));

            TextView name = text("", 16, R.color.text_primary);
            name.setTypeface(Typeface.DEFAULT_BOLD);
            name.setSingleLine(true);
            card.addView(name, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(32)
            ));
            TextView count = text("", 13, R.color.text_secondary);
            card.addView(count, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(24)
            ));
            return new FacetViewHolder(card, artwork, name, count);
        }

        @Override
        public void onBindViewHolder(FacetViewHolder holder, int position) {
            LibraryFacet facet = facets.get(position);
            loadArtwork(holder.artwork, facet.artworkTrack());
            holder.name.setText(facet.name);
            holder.count.setText(getString(R.string.library_facet_tracks, facet.trackCount));
            holder.itemView.setOnClickListener(view -> clickListener.onClick(facet));
        }

        @Override
        public int getItemCount() {
            return facets.size();
        }

        @Override
        public void onViewRecycled(FacetViewHolder holder) {
            holder.artwork.setTag(null);
            showArtworkPlaceholder(holder.artwork);
        }
    }

    private final class PlaylistAdapter extends RecyclerView.Adapter<PlaylistViewHolder> {
        private final List<LocalPlaylist> playlists = new ArrayList<>();
        private final PlaylistClickListener clickListener;

        PlaylistAdapter(PlaylistClickListener clickListener) {
            this.clickListener = clickListener;
        }

        void setPlaylists(List<LocalPlaylist> values) {
            playlists.clear();
            playlists.addAll(values);
            notifyDataSetChanged();
        }

        @Override
        public PlaylistViewHolder onCreateViewHolder(ViewGroup parent, int viewType) {
            LinearLayout row = new LinearLayout(NextActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(16), dp(4), dp(12), dp(4));
            row.setBackgroundColor(color(R.color.bg_secondary));
            row.setLayoutParams(new RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(73)
            ));

            TextView icon = text("▤", 30, R.color.accent);
            icon.setGravity(Gravity.CENTER);
            row.addView(icon, new LinearLayout.LayoutParams(dp(52), dp(64)));
            LinearLayout labels = new LinearLayout(NextActivity.this);
            labels.setOrientation(LinearLayout.VERTICAL);
            TextView name = text("", 17, R.color.text_primary);
            name.setTypeface(Typeface.DEFAULT_BOLD);
            TextView type = text("", 13, R.color.text_secondary);
            labels.addView(name);
            labels.addView(type);
            row.addView(labels, new LinearLayout.LayoutParams(0, dp(64), 1f));
            TextView arrow = text("›", 30, R.color.text_secondary);
            arrow.setGravity(Gravity.CENTER);
            row.addView(arrow, new LinearLayout.LayoutParams(dp(40), dp(64)));
            return new PlaylistViewHolder(row, icon, name, type);
        }

        @Override
        public void onBindViewHolder(PlaylistViewHolder holder, int position) {
            LocalPlaylist playlist = playlists.get(position);
            holder.icon.setText(playlist.isSystem ? "★" : "▤");
            holder.name.setText(playlist.name);
            holder.type.setText(playlist.isSystem
                    ? "Systemliste"
                    : "smart".equals(playlist.type) ? "Intelligent" : "Standard");
            holder.itemView.setOnClickListener(view -> clickListener.onClick(playlist));
        }

        @Override
        public int getItemCount() {
            return playlists.size();
        }
    }

    private static final class PlaylistViewHolder extends RecyclerView.ViewHolder {
        final TextView icon;
        final TextView name;
        final TextView type;

        PlaylistViewHolder(View itemView, TextView icon, TextView name, TextView type) {
            super(itemView);
            this.icon = icon;
            this.name = name;
            this.type = type;
        }
    }

    private static final class FacetViewHolder extends RecyclerView.ViewHolder {
        final ImageView artwork;
        final TextView name;
        final TextView count;

        FacetViewHolder(View itemView, ImageView artwork, TextView name, TextView count) {
            super(itemView);
            this.artwork = artwork;
            this.name = name;
            this.count = count;
        }
    }

    private static final class TrackViewHolder extends RecyclerView.ViewHolder {
        final ImageView artwork;
        final TextView title;
        final TextView artist;
        final TextView duration;
        final Button actions;

        TrackViewHolder(
                View itemView,
                ImageView artwork,
                TextView title,
                TextView artist,
                TextView duration,
                Button actions
        ) {
            super(itemView);
            this.artwork = artwork;
            this.title = title;
            this.artist = artist;
            this.duration = duration;
            this.actions = actions;
        }
    }

    private interface TrackClickListener {
        void onClick(long trackId);
    }

    private interface FacetClickListener {
        void onClick(LibraryFacet facet);
    }

    private interface PlaylistClickListener {
        void onClick(LocalPlaylist playlist);
    }
}
