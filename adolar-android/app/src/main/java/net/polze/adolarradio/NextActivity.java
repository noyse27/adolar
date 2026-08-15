package net.polze.adolarradio;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.support.v4.media.MediaBrowserCompat;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaControllerCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.drawerlayout.widget.DrawerLayout;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import net.polze.adolarradio.local.LocalLibraryRepository;
import net.polze.adolarradio.local.LocalLibraryScanner;
import net.polze.adolarradio.local.LocalTrack;

import java.util.ArrayList;
import java.util.List;

/** Offline-first launcher and local-library shell for Adolar Next. */
public class NextActivity extends Activity {
    private static final int REQUEST_MUSIC_TREE = 2001;
    private static final int REQUEST_MEDIA_PERMISSION = 2002;
    private static final String LOCAL_TRACK_PREFIX = "local:";

    private DrawerLayout drawerLayout;
    private RecyclerView trackList;
    private TrackAdapter adapter;
    private TextView statusView;
    private Button emptyAction;
    private LinearLayout scanPanel;
    private TextView scanPanelText;
    private TextView miniTitle;
    private TextView miniArtist;
    private Button miniPlayPause;
    private LocalLibraryRepository repository;
    private MediaBrowserCompat mediaBrowser;
    private MediaControllerCompat mediaController;
    private Long pendingTrackId;
    private Uri pendingScanUri;
    private boolean pendingScanAll;
    private boolean scanning;
    private boolean liveRefreshPending;
    private long lastLiveRefreshAt;

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
            };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        repository = LocalLibraryRepository.get(this);
        requestNotificationPermissionIfNeeded();
        buildUi();
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
        content.setOrientation(LinearLayout.VERTICAL);
        content.setBackgroundColor(color(R.color.bg_tertiary));
        DrawerLayout.LayoutParams contentParams = new DrawerLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        );
        drawerLayout.addView(content, contentParams);

        content.addView(buildToolbar(), new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(64)
        ));

        statusView = text("", 13, R.color.text_secondary);
        statusView.setPadding(dp(16), dp(8), dp(16), dp(8));
        content.addView(statusView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        FrameLayout libraryFrame = new FrameLayout(this);
        LinearLayout.LayoutParams libraryParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        );
        content.addView(libraryFrame, libraryParams);

        trackList = new RecyclerView(this);
        trackList.setLayoutManager(new LinearLayoutManager(this));
        trackList.setHasFixedSize(true);
        adapter = new TrackAdapter(this::playLocalTrack);
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

        content.addView(buildMiniPlayer(), new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(72)
        ));

        View drawer = buildDrawer();
        DrawerLayout.LayoutParams drawerParams = new DrawerLayout.LayoutParams(
                Math.min(dp(320), getResources().getDisplayMetrics().widthPixels - dp(48)),
                ViewGroup.LayoutParams.MATCH_PARENT
        );
        drawerParams.gravity = Gravity.START;
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
            view.setPadding(
                    bars.left,
                    bars.top,
                    bars.right,
                    Math.max(bars.bottom, keyboard.bottom)
            );
            return windowInsets;
        });
        ViewCompat.requestApplyInsets(drawerLayout);
    }

    private View buildToolbar() {
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(8), 0, dp(8), 0);
        toolbar.setBackgroundColor(color(R.color.bg_primary));

        ImageButton rocket = new ImageButton(this);
        rocket.setImageResource(R.drawable.ic_launcher_foreground);
        rocket.setScaleType(ImageButton.ScaleType.CENTER_INSIDE);
        rocket.setBackgroundColor(Color.TRANSPARENT);
        rocket.setContentDescription(getString(R.string.app_name));
        rocket.setOnClickListener(view -> drawerLayout.openDrawer(Gravity.START));
        toolbar.addView(rocket, new LinearLayout.LayoutParams(dp(52), dp(52)));

        TextView icon = text("♫", 30, R.color.accent);
        icon.setGravity(Gravity.CENTER);
        toolbar.addView(icon, new LinearLayout.LayoutParams(dp(48), dp(52)));

        TextView title = text(getString(R.string.library_tracks), 24, R.color.text_primary);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(52), 1f));

        Button overflow = new Button(this);
        overflow.setText("⋮");
        overflow.setTextSize(26);
        overflow.setTextColor(color(R.color.text_primary));
        overflow.setBackgroundColor(Color.TRANSPARENT);
        overflow.setContentDescription(getString(R.string.settings_button));
        overflow.setOnClickListener(this::showOverflow);
        toolbar.addView(overflow, new LinearLayout.LayoutParams(dp(52), dp(52)));
        return toolbar;
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
        rocket.setOnClickListener(view -> drawerLayout.closeDrawer(Gravity.START));
        header.addView(rocket, new LinearLayout.LayoutParams(dp(62), dp(62)));
        TextView brand = text(getString(R.string.app_name), 23, R.color.accent_light);
        brand.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(brand, new LinearLayout.LayoutParams(0, dp(62), 1f));
        drawer.addView(header, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(70)
        ));

        addDrawerHeading(drawer, "SCHNELLZUGRIFF");
        addPendingDrawerItem(drawer, R.string.library_drawer_favorites);
        addPendingDrawerItem(drawer, R.string.library_drawer_recently_added);
        addPendingDrawerItem(drawer, R.string.library_drawer_most_played);

        addDrawerHeading(drawer, "BIBLIOTHEK");
        addPendingDrawerItem(drawer, R.string.library_drawer_search);
        addPendingDrawerItem(drawer, R.string.library_drawer_albums);
        addPendingDrawerItem(drawer, R.string.library_drawer_artists);
        addPendingDrawerItem(drawer, R.string.library_drawer_genres);
        addPendingDrawerItem(drawer, R.string.library_drawer_playlists);
        addDrawerItem(drawer, getString(R.string.library_drawer_folders), view -> {
            drawerLayout.closeDrawer(Gravity.START);
            chooseMusicFolder();
        });
        addDrawerItem(drawer, getString(R.string.library_tracks), view -> {
            drawerLayout.closeDrawer(Gravity.START);
            refreshTracks();
        });
        addDrawerItem(drawer, getString(R.string.library_open_radios), view -> openRadios());
        addPendingDrawerItem(drawer, R.string.library_drawer_sync);
        return scroll;
    }

    private View buildMiniPlayer() {
        LinearLayout mini = new LinearLayout(this);
        mini.setOrientation(LinearLayout.HORIZONTAL);
        mini.setGravity(Gravity.CENTER_VERTICAL);
        mini.setPadding(dp(16), dp(6), dp(8), dp(6));
        mini.setBackgroundColor(color(R.color.bg_primary));
        LinearLayout labels = new LinearLayout(this);
        labels.setOrientation(LinearLayout.VERTICAL);
        miniTitle = text(getString(R.string.library_now_playing_empty), 16, R.color.text_primary);
        miniTitle.setTypeface(Typeface.DEFAULT_BOLD);
        miniArtist = text("Adolar Next", 13, R.color.text_secondary);
        labels.addView(miniTitle);
        labels.addView(miniArtist);
        mini.addView(labels, new LinearLayout.LayoutParams(0, dp(60), 1f));

        miniPlayPause = new Button(this);
        miniPlayPause.setText(R.string.play);
        miniPlayPause.setTextSize(20);
        miniPlayPause.setTextColor(Color.WHITE);
        miniPlayPause.setBackgroundColor(color(R.color.accent_deep));
        miniPlayPause.setOnClickListener(view -> togglePlayback());
        mini.addView(miniPlayPause, new LinearLayout.LayoutParams(dp(56), dp(56)));
        return mini;
    }

    private void showOverflow(View anchor) {
        PopupMenu menu = new PopupMenu(this, anchor);
        menu.getMenu().add(getString(R.string.library_choose_folder));
        menu.getMenu().add(getString(R.string.library_rescan));
        menu.getMenu().add(getString(R.string.library_open_radios));
        menu.setOnMenuItemClickListener(item -> {
            String title = item.getTitle().toString();
            if (title.equals(getString(R.string.library_choose_folder))) {
                chooseMusicFolder();
            } else if (title.equals(getString(R.string.library_rescan))) {
                scanAll();
            } else {
                openRadios();
            }
            return true;
        });
        menu.show();
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
            drawerLayout.closeDrawer(Gravity.START);
            Toast.makeText(this, R.string.library_feature_pending, Toast.LENGTH_SHORT).show();
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
        int flags = data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION;
        try {
            getContentResolver().takePersistableUriPermission(treeUri, flags);
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
        scanPanel.setVisibility(adapter.getItemCount() == 0 ? View.VISIBLE : View.GONE);
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
                refreshTracks();
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

    private void showTracks(List<LocalTrack> tracks) {
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
        mediaController.getTransportControls().playFromMediaId(
                LOCAL_TRACK_PREFIX + trackId, null
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

    private void updateMiniPlayer(
            MediaMetadataCompat metadata, PlaybackStateCompat playbackState
    ) {
        if (miniTitle == null) return;
        if (metadata == null || metadata.getDescription().getTitle() == null) {
            miniTitle.setText(R.string.library_now_playing_empty);
            miniArtist.setText(R.string.app_name);
        } else {
            miniTitle.setText(metadata.getDescription().getTitle());
            CharSequence artist = metadata.getDescription().getSubtitle();
            miniArtist.setText(artist == null || artist.length() == 0
                    ? getString(R.string.library_unknown_artist) : artist);
        }
        boolean playing = playbackState != null
                && playbackState.getState() == PlaybackStateCompat.STATE_PLAYING;
        miniPlayPause.setText(playing ? R.string.pause : R.string.play);
    }

    private void openRadios() {
        drawerLayout.closeDrawer(Gravity.START);
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
        if (drawerLayout != null && drawerLayout.isDrawerOpen(Gravity.START)) {
            drawerLayout.closeDrawer(Gravity.START);
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

        @Override
        public TrackViewHolder onCreateViewHolder(ViewGroup parent, int viewType) {
            LinearLayout row = new LinearLayout(NextActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(16), dp(8), dp(8), dp(8));
            row.setBackgroundColor(color(R.color.bg_secondary));

            LinearLayout labels = new LinearLayout(NextActivity.this);
            labels.setOrientation(LinearLayout.VERTICAL);
            TextView title = text("", 17, R.color.text_primary);
            title.setTypeface(Typeface.DEFAULT_BOLD);
            title.setSingleLine(true);
            TextView artist = text("", 14, R.color.text_secondary);
            artist.setSingleLine(true);
            labels.addView(title);
            labels.addView(artist);
            row.addView(labels, new LinearLayout.LayoutParams(0, dp(64), 1f));

            TextView duration = text("", 14, R.color.text_secondary);
            duration.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
            row.addView(duration, new LinearLayout.LayoutParams(dp(58), dp(64)));
            return new TrackViewHolder(row, title, artist, duration);
        }

        @Override
        public void onBindViewHolder(TrackViewHolder holder, int position) {
            LocalTrack track = tracks.get(position);
            holder.title.setText(track.title);
            holder.artist.setText(track.artist);
            holder.duration.setText(formatDuration(track.durationSeconds));
            holder.itemView.setOnClickListener(view -> clickListener.onClick(track.id));
        }

        @Override
        public int getItemCount() {
            return tracks.size();
        }
    }

    private static final class TrackViewHolder extends RecyclerView.ViewHolder {
        final TextView title;
        final TextView artist;
        final TextView duration;

        TrackViewHolder(View itemView, TextView title, TextView artist, TextView duration) {
            super(itemView);
            this.title = title;
            this.artist = artist;
            this.duration = duration;
        }
    }

    private interface TrackClickListener {
        void onClick(long trackId);
    }
}
