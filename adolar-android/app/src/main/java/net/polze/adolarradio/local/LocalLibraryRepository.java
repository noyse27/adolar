package net.polze.adolarradio.local;

import android.content.Context;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Application-scoped boundary between UI, Room, and the synchronous scanner. */
public final class LocalLibraryRepository {
    public interface TracksCallback {
        void onTracks(List<LocalTrack> tracks);
    }

    public interface FacetsCallback {
        void onFacets(List<LibraryFacet> facets);
    }

    public enum FacetType {
        ALBUM, ARTIST, GENRE
    }

    public interface ScanCallback {
        void onProgress(LocalLibraryScanner.ScanProgress progress);
        void onComplete(LocalLibraryScanner.ScanProgress progress);
    }

    private static volatile LocalLibraryRepository instance;

    private final LibraryDao dao;
    private final LocalLibraryScanner scanner;
    private final ExecutorService scanExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService queryExecutor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private LocalLibraryRepository(Context context) {
        dao = LocalLibraryDatabase.get(context).libraryDao();
        scanner = new LocalLibraryScanner(context, dao);
    }

    public static LocalLibraryRepository get(Context context) {
        if (instance == null) {
            synchronized (LocalLibraryRepository.class) {
                if (instance == null) {
                    instance = new LocalLibraryRepository(context.getApplicationContext());
                }
            }
        }
        return instance;
    }

    public void loadTracks(TracksCallback callback) {
        queryExecutor.execute(() -> loadTracks(false, callback));
    }

    public void loadTrackPreview(TracksCallback callback) {
        queryExecutor.execute(() -> loadTracks(true, callback));
    }

    public void searchTracks(String query, TracksCallback callback) {
        queryExecutor.execute(() -> postTracks(dao.searchTracks(query), callback));
    }

    public void loadFacets(FacetType type, FacetsCallback callback) {
        queryExecutor.execute(() -> {
            List<LibraryFacet> facets;
            if (type == FacetType.ALBUM) {
                facets = dao.getAlbums();
            } else if (type == FacetType.ARTIST) {
                facets = dao.getArtists();
            } else {
                facets = dao.getGenres();
            }
            mainHandler.post(() -> callback.onFacets(facets));
        });
    }

    public void loadTracksForFacet(
            FacetType type, String name, TracksCallback callback
    ) {
        queryExecutor.execute(() -> {
            List<LocalTrack> tracks;
            if (type == FacetType.ALBUM) {
                tracks = dao.getTracksByAlbum(name);
            } else if (type == FacetType.ARTIST) {
                tracks = dao.getTracksByArtist(name);
            } else {
                tracks = dao.getTracksByGenre(name);
            }
            postTracks(tracks, callback);
        });
    }

    private void loadTracks(boolean preview, TracksCallback callback) {
        List<LocalTrack> tracks;
        try {
            tracks = preview ? dao.getActiveTrackPreview(200) : dao.getActiveTracks();
        } catch (RuntimeException error) {
            tracks = Collections.emptyList();
        }
        List<LocalTrack> result = tracks;
        mainHandler.post(() -> callback.onTracks(result));
    }

    private void postTracks(List<LocalTrack> tracks, TracksCallback callback) {
        List<LocalTrack> result = tracks == null ? Collections.emptyList() : tracks;
        mainHandler.post(() -> callback.onTracks(result));
    }

    public void scanRoot(Uri treeUri, ScanCallback callback) {
        scanExecutor.execute(() -> {
            LocalLibraryScanner.ScanProgress result = scanner.scan(
                    treeUri,
                    progress -> mainHandler.post(() -> callback.onProgress(progress))
            );
            mainHandler.post(() -> callback.onComplete(result));
        });
    }

    public void scanAll(ScanCallback callback) {
        scanExecutor.execute(() -> {
            List<LibraryRoot> roots = dao.getRoots();
            if (roots.isEmpty()) {
                LocalLibraryScanner.ScanProgress empty = new LocalLibraryScanner.ScanProgress();
                mainHandler.post(() -> callback.onComplete(empty));
                return;
            }
            LocalLibraryScanner.ScanProgress aggregate = new LocalLibraryScanner.ScanProgress();
            for (LibraryRoot root : roots) {
                LocalLibraryScanner.ScanProgress result = scanner.scan(
                        Uri.parse(root.treeUri),
                        progress -> mainHandler.post(() -> callback.onProgress(progress))
                );
                aggregate.visited += result.visited;
                aggregate.indexed += result.indexed;
                aggregate.unchanged += result.unchanged;
                aggregate.errors += result.errors;
                aggregate.missing += result.missing;
            }
            mainHandler.post(() -> callback.onComplete(aggregate));
        });
    }
}
