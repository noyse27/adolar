package net.polze.adolarradio.local;

import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.Context;
import android.database.Cursor;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.MediaStore;
import android.util.Log;

import androidx.documentfile.provider.DocumentFile;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Synchronous hybrid MediaStore/SAF scanner. Run it off the main thread. */
public final class LocalLibraryScanner {
    private static final String LOG_TAG = "AdolarLibraryScan";
    private static final Set<String> AUDIO_EXTENSIONS = new HashSet<>(Arrays.asList(
            "mp3", "flac", "m4a", "ogg", "opus", "aac", "wav"
    ));

    public interface ProgressListener {
        void onProgress(ScanProgress progress);
    }

    public static final class ScanProgress {
        public int visited;
        public int indexed;
        public int unchanged;
        public int errors;
        public int missing;
        public String currentName = "";

        ScanProgress copy() {
            ScanProgress copy = new ScanProgress();
            copy.visited = visited;
            copy.indexed = indexed;
            copy.unchanged = unchanged;
            copy.errors = errors;
            copy.missing = missing;
            copy.currentName = currentName;
            return copy;
        }
    }

    private final Context context;
    private final LibraryDao dao;

    public LocalLibraryScanner(Context context, LibraryDao dao) {
        this.context = context.getApplicationContext();
        this.dao = dao;
    }

    public ScanProgress scan(Uri treeUri, ProgressListener listener) {
        long scanId = System.currentTimeMillis();
        ScanProgress progress = new ScanProgress();
        String rootUri = treeUri.toString();
        LibraryRoot savedRoot = dao.getRoot(rootUri);
        DocumentFile root = DocumentFile.fromTreeUri(context, treeUri);
        if (savedRoot == null) {
            savedRoot = new LibraryRoot();
            savedRoot.treeUri = rootUri;
            savedRoot.addedAt = scanId;
        }
        savedRoot.displayName = root == null || root.getName() == null
                ? rootUri : root.getName();
        savedRoot.lastScanStatus = "scanning";
        savedRoot.lastScanError = null;
        dao.saveRoot(savedRoot);

        if (root == null || !root.exists() || !root.canRead()) {
            savedRoot.lastScanAt = System.currentTimeMillis();
            savedRoot.lastScanStatus = "failed";
            savedRoot.lastScanError = "Der Musikordner ist nicht mehr lesbar.";
            dao.saveRoot(savedRoot);
            progress.errors++;
            notifyProgress(listener, progress);
            return progress;
        }

        Map<String, LocalTrack> byDocumentId = new HashMap<>();
        Map<String, LocalTrack> byDocumentUri = new HashMap<>();
        for (LocalTrack track : dao.getTracksForRoot(rootUri)) {
            if (track.documentId != null) byDocumentId.put(track.documentId, track);
            byDocumentUri.put(track.documentUri, track);
        }

        // MediaStore already contains Android's extracted audio tags. Reading
        // one cursor is dramatically cheaper than opening every audio file.
        // A missing permission/provider simply leaves all work to SAF below.
        indexFromMediaStore(
                treeUri, rootUri, scanId, progress, listener,
                byDocumentId, byDocumentUri
        );

        // SAF remains authoritative for folder membership and finds freshly
        // copied files that Android has not added to MediaStore yet. Files seen
        // above are skipped without opening them a second time.
        boolean traversalComplete = traverseSafTree(
                treeUri, rootUri, scanId, progress, listener,
                byDocumentId, byDocumentUri
        );

        if (traversalComplete) {
            progress.missing = dao.markUnseenMissing(rootUri, scanId);
        }
        savedRoot.lastScanAt = System.currentTimeMillis();
        savedRoot.lastScanStatus = traversalComplete
                ? (progress.errors == 0 ? "complete" : "partial")
                : "partial";
        savedRoot.lastScanError = progress.errors == 0
                ? null : progress.errors + " Datei(en) oder Ordner konnten nicht gelesen werden.";
        dao.saveRoot(savedRoot);
        progress.currentName = "";
        notifyProgress(listener, progress);
        return progress;
    }

    private void indexFromMediaStore(
            Uri treeUri,
            String rootUri,
            long scanId,
            ScanProgress progress,
            ProgressListener listener,
            Map<String, LocalTrack> byDocumentId,
            Map<String, LocalTrack> byDocumentUri
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                || !"com.android.externalstorage.documents".equals(treeUri.getAuthority())) {
            return;
        }
        final String treeDocumentId;
        try {
            treeDocumentId = DocumentsContract.getTreeDocumentId(treeUri);
        } catch (RuntimeException error) {
            return;
        }
        int separator = treeDocumentId.indexOf(':');
        if (separator < 0) return;

        String documentVolume = treeDocumentId.substring(0, separator);
        String volumeName = "primary".equalsIgnoreCase(documentVolume)
                ? MediaStore.VOLUME_EXTERNAL_PRIMARY
                : documentVolume.toLowerCase(Locale.ROOT);
        String selectedPath = normalizeDirectory(treeDocumentId.substring(separator + 1));
        Uri collection;
        try {
            collection = MediaStore.Audio.Media.getContentUri(volumeName);
        } catch (RuntimeException error) {
            return;
        }

        List<String> projection = new ArrayList<>(Arrays.asList(
                MediaStore.Audio.Media._ID,
                MediaStore.Audio.Media.DISPLAY_NAME,
                MediaStore.Audio.Media.MIME_TYPE,
                MediaStore.Audio.Media.SIZE,
                MediaStore.Audio.Media.DATE_MODIFIED,
                MediaStore.Audio.Media.DATE_ADDED,
                MediaStore.Audio.Media.DURATION,
                MediaStore.Audio.Media.TITLE,
                MediaStore.Audio.Media.ARTIST,
                MediaStore.Audio.Media.ALBUM,
                MediaStore.Audio.Media.YEAR,
                MediaStore.Audio.Media.TRACK,
                MediaStore.Audio.Media.RELATIVE_PATH
        ));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            projection.add(MediaStore.Audio.AudioColumns.ALBUM_ARTIST);
            projection.add(MediaStore.Audio.AudioColumns.GENRE);
            projection.add(MediaStore.Audio.AudioColumns.BITRATE);
        }

        List<String> clauses = new ArrayList<>();
        List<String> arguments = new ArrayList<>();
        clauses.add(MediaStore.Audio.Media.IS_PENDING + "=0");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            clauses.add(MediaStore.Audio.Media.IS_TRASHED + "=0");
        }
        if (!selectedPath.isEmpty()) {
            clauses.add("(" + MediaStore.Audio.Media.RELATIVE_PATH + "=? OR "
                    + MediaStore.Audio.Media.RELATIVE_PATH + " LIKE ? ESCAPE '!')");
            arguments.add(selectedPath);
            arguments.add(escapeLike(selectedPath) + "%");
        }

        int visitedBefore = progress.visited;
        try (Cursor cursor = context.getContentResolver().query(
                collection,
                projection.toArray(new String[0]),
                joinWithAnd(clauses),
                arguments.toArray(new String[0]),
                null
        )) {
            if (cursor == null) return;
            while (cursor.moveToNext()) {
                String displayName = stringValue(cursor, MediaStore.Audio.Media.DISPLAY_NAME);
                String mimeType = stringValue(cursor, MediaStore.Audio.Media.MIME_TYPE);
                if (!isSupportedAudio(displayName, mimeType)) continue;

                String relativePath = normalizeDirectory(
                        stringValue(cursor, MediaStore.Audio.Media.RELATIVE_PATH)
                );
                String documentId = documentVolume + ":" + relativePath + displayName;
                Uri documentUri;
                try {
                    documentUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, documentId);
                } catch (RuntimeException error) {
                    long mediaId = longValue(cursor, MediaStore.Audio.Media._ID);
                    documentUri = ContentUris.withAppendedId(collection, mediaId);
                }

                progress.visited++;
                progress.currentName = value(displayName, "Unbekannte Datei");
                LocalTrack existing = byDocumentId.get(documentId);
                if (existing == null) existing = byDocumentUri.get(documentUri.toString());
                long modified = longValue(cursor, MediaStore.Audio.Media.DATE_MODIFIED) * 1000L;
                long size = longValue(cursor, MediaStore.Audio.Media.SIZE);
                long now = System.currentTimeMillis();
                if (existing != null && existing.modifiedAt == modified
                        && existing.sizeBytes == size && !existing.missing) {
                    dao.touchTrack(existing.id, scanId, now);
                    existing.lastSeenScan = scanId;
                    existing.missing = false;
                    progress.unchanged++;
                } else {
                    LocalTrack track = new LocalTrack();
                    track.id = existing == null ? 0 : existing.id;
                    track.rootUri = rootUri;
                    track.documentUri = documentUri.toString();
                    track.documentId = documentId;
                    track.displayName = value(displayName, "Unbekannte Datei");
                    track.mimeType = value(mimeType, "audio/*");
                    track.title = value(
                            stringValue(cursor, MediaStore.Audio.Media.TITLE),
                            stripExtension(track.displayName)
                    );
                    track.artist = value(
                            stringValue(cursor, MediaStore.Audio.Media.ARTIST),
                            "Unbekannter Interpret"
                    );
                    track.album = value(stringValue(cursor, MediaStore.Audio.Media.ALBUM), "");
                    track.albumArtist = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
                            ? value(stringValue(
                                    cursor, MediaStore.Audio.AudioColumns.ALBUM_ARTIST
                            ), "") : "";
                    track.genre = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
                            ? value(stringValue(cursor, MediaStore.Audio.AudioColumns.GENRE), "")
                            : "";
                    track.year = nullableInteger(cursor, MediaStore.Audio.Media.YEAR);
                    track.trackNo = normalizeTrackNumber(
                            nullableInteger(cursor, MediaStore.Audio.Media.TRACK)
                    );
                    track.durationSeconds = longValue(
                            cursor, MediaStore.Audio.Media.DURATION
                    ) / 1000L;
                    track.bitrateKbps = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
                            ? (int) (longValue(
                                    cursor, MediaStore.Audio.AudioColumns.BITRATE
                            ) / 1000L) : 0;
                    track.sizeBytes = size;
                    track.modifiedAt = modified;
                    long mediaAddedAt = longValue(cursor, MediaStore.Audio.Media.DATE_ADDED) * 1000L;
                    track.addedAt = existing == null
                            ? (mediaAddedAt > 0 ? mediaAddedAt : now) : existing.addedAt;
                    track.indexedAt = now;
                    track.lastSeenScan = scanId;
                    track.missing = false;
                    saveTrack(track, existing, byDocumentId, byDocumentUri);
                    progress.indexed++;
                }
                if (progress.visited == 1 || progress.visited % 100 == 0) {
                    notifyProgress(listener, progress);
                }
            }
            Log.i(LOG_TAG, "MediaStore indexed " + (progress.visited - visitedBefore)
                    + " tracks for " + treeDocumentId);
        } catch (RuntimeException error) {
            // No media permission, unsupported volume, or vendor-specific
            // projection: the SAF pass below still performs a complete scan.
            Log.w(LOG_TAG, "MediaStore acceleration unavailable", error);
        }
    }

    private boolean traverseSafTree(
            Uri treeUri,
            String rootUri,
            long scanId,
            ScanProgress progress,
            ProgressListener listener,
            Map<String, LocalTrack> byDocumentId,
            Map<String, LocalTrack> byDocumentUri
    ) {
        String rootDocumentId;
        try {
            rootDocumentId = DocumentsContract.getTreeDocumentId(treeUri);
        } catch (RuntimeException error) {
            progress.errors++;
            return false;
        }
        ArrayDeque<String> pending = new ArrayDeque<>();
        pending.add(rootDocumentId);
        boolean complete = true;
        String[] projection = {
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                DocumentsContract.Document.COLUMN_SIZE,
                DocumentsContract.Document.COLUMN_LAST_MODIFIED
        };
        ContentResolver resolver = context.getContentResolver();

        while (!pending.isEmpty()) {
            String directoryId = pending.removeFirst();
            Uri childrenUri;
            try {
                childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(
                        treeUri, directoryId
                );
            } catch (RuntimeException error) {
                progress.errors++;
                complete = false;
                continue;
            }
            try (Cursor cursor = resolver.query(childrenUri, projection, null, null, null)) {
                if (cursor == null) {
                    progress.errors++;
                    complete = false;
                    continue;
                }
                while (cursor.moveToNext()) {
                    String documentId = stringValue(
                            cursor, DocumentsContract.Document.COLUMN_DOCUMENT_ID
                    );
                    String name = stringValue(
                            cursor, DocumentsContract.Document.COLUMN_DISPLAY_NAME
                    );
                    String mime = stringValue(
                            cursor, DocumentsContract.Document.COLUMN_MIME_TYPE
                    );
                    if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                        if (documentId != null) pending.addLast(documentId);
                        continue;
                    }
                    if (documentId == null || !isSupportedAudio(name, mime)) continue;

                    Uri documentUri = DocumentsContract.buildDocumentUriUsingTree(
                            treeUri, documentId
                    );
                    LocalTrack existing = byDocumentId.get(documentId);
                    if (existing == null) existing = byDocumentUri.get(documentUri.toString());
                    if (existing != null && existing.lastSeenScan == scanId) {
                        continue; // Already handled by the MediaStore cursor.
                    }

                    progress.visited++;
                    progress.currentName = value(name, "Unbekannte Datei");
                    indexSafFile(
                            rootUri,
                            documentUri,
                            documentId,
                            name,
                            mime,
                            longValue(cursor, DocumentsContract.Document.COLUMN_LAST_MODIFIED),
                            longValue(cursor, DocumentsContract.Document.COLUMN_SIZE),
                            scanId,
                            progress,
                            existing,
                            byDocumentId,
                            byDocumentUri
                    );
                    if (progress.visited == 1 || progress.visited % 20 == 0) {
                        notifyProgress(listener, progress);
                    }
                }
            } catch (RuntimeException error) {
                progress.errors++;
                complete = false;
            }
        }
        Log.i(LOG_TAG, "SAF verification completed; total visited=" + progress.visited);
        return complete;
    }

    private void indexSafFile(
            String rootUri,
            Uri documentUri,
            String documentId,
            String displayName,
            String mimeType,
            long modified,
            long size,
            long scanId,
            ScanProgress progress,
            LocalTrack existing,
            Map<String, LocalTrack> byDocumentId,
            Map<String, LocalTrack> byDocumentUri
    ) {
        modified = Math.max(0L, modified);
        size = Math.max(0L, size);
        long now = System.currentTimeMillis();
        if (existing != null && existing.modifiedAt == modified
                && existing.sizeBytes == size && !existing.missing) {
            dao.touchTrack(existing.id, scanId, now);
            existing.lastSeenScan = scanId;
            existing.missing = false;
            progress.unchanged++;
            return;
        }
        if (existing != null) {
            dao.touchTrack(existing.id, scanId, now);
            existing.lastSeenScan = scanId;
        }
        try {
            LocalTrack track = readMetadata(documentUri, displayName);
            track.id = existing == null ? 0 : existing.id;
            track.rootUri = rootUri;
            track.documentUri = documentUri.toString();
            track.documentId = documentId;
            track.displayName = value(displayName, "Unbekannte Datei");
            track.mimeType = value(mimeType, "audio/*");
            track.sizeBytes = size;
            track.modifiedAt = modified;
            track.addedAt = existing == null ? now : existing.addedAt;
            track.indexedAt = now;
            track.lastSeenScan = scanId;
            track.missing = false;
            saveTrack(track, existing, byDocumentId, byDocumentUri);
            progress.indexed++;
        } catch (Exception error) {
            progress.errors++;
        }
    }

    private void saveTrack(
            LocalTrack track,
            LocalTrack existing,
            Map<String, LocalTrack> byDocumentId,
            Map<String, LocalTrack> byDocumentUri
    ) {
        if (existing == null) {
            track.id = dao.insertTrack(track);
        } else {
            dao.updateTrack(track);
            byDocumentUri.remove(existing.documentUri);
            if (existing.documentId != null) byDocumentId.remove(existing.documentId);
        }
        if (track.documentId != null) byDocumentId.put(track.documentId, track);
        byDocumentUri.put(track.documentUri, track);
    }

    private LocalTrack readMetadata(Uri uri, String displayName) throws Exception {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try (ParcelFileDescriptor descriptor = context.getContentResolver()
                .openFileDescriptor(uri, "r")) {
            if (descriptor == null) {
                throw new IllegalStateException("Datei konnte nicht geöffnet werden");
            }
            retriever.setDataSource(descriptor.getFileDescriptor());
            LocalTrack track = new LocalTrack();
            String filename = value(displayName, "Unbekannter Titel");
            track.title = value(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE),
                    stripExtension(filename)
            );
            track.artist = value(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST),
                    "Unbekannter Interpret"
            );
            track.album = value(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUM), ""
            );
            track.albumArtist = value(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST), ""
            );
            track.genre = value(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_GENRE), ""
            );
            track.year = parseInteger(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_YEAR)
            );
            track.trackNo = parseFractionInteger(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CD_TRACK_NUMBER)
            );
            track.durationSeconds = parseLong(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
            ) / 1000L;
            track.bitrateKbps = (int) (parseLong(
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_BITRATE)
            ) / 1000L);
            return track;
        } finally {
            try {
                retriever.release();
            } catch (RuntimeException ignored) {
                // Some vendor retrievers throw while releasing malformed media.
            }
        }
    }

    private static boolean isSupportedAudio(String name, String mime) {
        if (mime != null && mime.toLowerCase(Locale.ROOT).startsWith("audio/")) return true;
        if (name == null) return false;
        int dot = name.lastIndexOf('.');
        return dot >= 0 && AUDIO_EXTENSIONS.contains(
                name.substring(dot + 1).toLowerCase(Locale.ROOT)
        );
    }

    private static String normalizeDirectory(String path) {
        if (path == null || path.isEmpty()) return "";
        String normalized = path.replace('\\', '/');
        while (normalized.startsWith("/")) normalized = normalized.substring(1);
        return normalized.endsWith("/") ? normalized : normalized + "/";
    }

    private static String joinWithAnd(List<String> clauses) {
        StringBuilder value = new StringBuilder();
        for (String clause : clauses) {
            if (value.length() > 0) value.append(" AND ");
            value.append(clause);
        }
        return value.toString();
    }

    private static String escapeLike(String value) {
        return value.replace("!", "!!")
                .replace("%", "!%")
                .replace("_", "!_");
    }

    private static String stringValue(Cursor cursor, String column) {
        int index = cursor.getColumnIndex(column);
        return index < 0 || cursor.isNull(index) ? null : cursor.getString(index);
    }

    private static long longValue(Cursor cursor, String column) {
        int index = cursor.getColumnIndex(column);
        return index < 0 || cursor.isNull(index) ? 0L : cursor.getLong(index);
    }

    private static Integer nullableInteger(Cursor cursor, String column) {
        int index = cursor.getColumnIndex(column);
        return index < 0 || cursor.isNull(index) ? null : cursor.getInt(index);
    }

    private static Integer normalizeTrackNumber(Integer track) {
        if (track == null || track <= 0) return null;
        return track >= 1000 ? track % 1000 : track;
    }

    private static String stripExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot > 0 ? filename.substring(0, dot) : filename;
    }

    private static String value(String value, String fallback) {
        if (value == null || value.trim().isEmpty()
                || MediaStore.UNKNOWN_STRING.equals(value.trim())) return fallback;
        return value.trim();
    }

    private static Integer parseInteger(String value) {
        if (value == null) return null;
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private static Integer parseFractionInteger(String value) {
        if (value == null) return null;
        String first = value.split("/", 2)[0];
        return parseInteger(first);
    }

    private static long parseLong(String value) {
        if (value == null) return 0L;
        try {
            return Long.parseLong(value.trim());
        } catch (NumberFormatException ignored) {
            return 0L;
        }
    }

    private static void notifyProgress(ProgressListener listener, ScanProgress progress) {
        if (listener != null) listener.onProgress(progress.copy());
    }
}
