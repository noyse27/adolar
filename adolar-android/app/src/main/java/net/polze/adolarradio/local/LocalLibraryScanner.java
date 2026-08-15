package net.polze.adolarradio.local;

import android.content.Context;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;

import androidx.documentfile.provider.DocumentFile;

import java.io.File;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Synchronous scanner. Callers are responsible for running it off the main thread. */
public final class LocalLibraryScanner {
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

        boolean traversalComplete = true;
        ArrayDeque<DocumentFile> pending = new ArrayDeque<>();
        pending.add(root);
        while (!pending.isEmpty()) {
            DocumentFile directory = pending.removeFirst();
            DocumentFile[] children;
            try {
                children = directory.listFiles();
            } catch (RuntimeException error) {
                progress.errors++;
                traversalComplete = false;
                notifyProgress(listener, progress);
                continue;
            }
            for (DocumentFile child : children) {
                if (child.isDirectory()) {
                    pending.addLast(child);
                    continue;
                }
                if (!child.isFile() || !isSupportedAudio(child)) {
                    continue;
                }
                progress.visited++;
                progress.currentName = value(child.getName(), "Unbekannte Datei");
                indexFile(rootUri, child, scanId, progress);
                if (progress.visited == 1 || progress.visited % 20 == 0) {
                    notifyProgress(listener, progress);
                }
            }
        }

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

    private void indexFile(
            String rootUri, DocumentFile document, long scanId, ScanProgress progress
    ) {
        String documentUri = document.getUri().toString();
        LocalTrack existing = dao.getTrackByDocumentUri(documentUri);
        long modified = Math.max(0L, document.lastModified());
        long size = Math.max(0L, document.length());
        long now = System.currentTimeMillis();
        if (existing != null && existing.modifiedAt == modified
                && existing.sizeBytes == size && !existing.missing) {
            dao.touchTrack(existing.id, scanId, now);
            progress.unchanged++;
            return;
        }

        // A changed, already known file must not become missing just because one
        // malformed tag cannot be read during this pass.
        if (existing != null) {
            dao.touchTrack(existing.id, scanId, now);
        }
        try {
            LocalTrack track = readMetadata(document);
            track.id = existing == null ? 0 : existing.id;
            track.rootUri = rootUri;
            track.documentUri = documentUri;
            track.documentId = documentId(document.getUri());
            track.displayName = value(document.getName(), "Unbekannte Datei");
            track.mimeType = value(document.getType(), "audio/*");
            track.sizeBytes = size;
            track.modifiedAt = modified;
            track.addedAt = existing == null ? now : existing.addedAt;
            track.indexedAt = now;
            track.lastSeenScan = scanId;
            track.missing = false;
            if (existing == null) {
                track.id = dao.insertTrack(track);
            } else {
                dao.updateTrack(track);
            }
            progress.indexed++;
        } catch (Exception error) {
            progress.errors++;
        }
    }

    private LocalTrack readMetadata(DocumentFile document) throws Exception {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try (ParcelFileDescriptor descriptor = context.getContentResolver()
                .openFileDescriptor(document.getUri(), "r")) {
            if (descriptor == null) {
                throw new IllegalStateException("Datei konnte nicht geöffnet werden");
            }
            retriever.setDataSource(descriptor.getFileDescriptor());
            LocalTrack track = new LocalTrack();
            String filename = value(document.getName(), "Unbekannter Titel");
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

    private static boolean isSupportedAudio(DocumentFile document) {
        String mime = document.getType();
        if (mime != null && mime.toLowerCase(Locale.ROOT).startsWith("audio/")) {
            return true;
        }
        String name = document.getName();
        if (name == null) return false;
        int dot = name.lastIndexOf('.');
        return dot >= 0 && AUDIO_EXTENSIONS.contains(
                name.substring(dot + 1).toLowerCase(Locale.ROOT)
        );
    }

    private static String documentId(Uri uri) {
        try {
            return DocumentsContract.getDocumentId(uri);
        } catch (RuntimeException ignored) {
            return uri.toString();
        }
    }

    private static String stripExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot > 0 ? filename.substring(0, dot) : filename;
    }

    private static String value(String value, String fallback) {
        if (value == null || value.trim().isEmpty()) return fallback;
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
