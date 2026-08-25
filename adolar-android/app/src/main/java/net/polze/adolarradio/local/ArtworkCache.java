package net.polze.adolarradio.local;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.util.LruCache;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Persistent, size-bounded album artwork extraction independent of the music scan. */
public final class ArtworkCache {
    public static final int RESULT_CACHED = 0;
    public static final int RESULT_FOUND = 1;
    public static final int RESULT_MISSING = 2;
    public static final int RESULT_ERROR = 3;

    public interface Callback {
        void onArtwork(String key, Bitmap bitmap);
    }

    private static final int MAX_ARTWORK_EDGE = 720;
    private static volatile ArtworkCache instance;

    private final Context context;
    private final File directory;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService visibleExecutor = new ThreadPoolExecutor(
            2, 2, 20L, TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(64),
            new ThreadPoolExecutor.DiscardOldestPolicy()
    );
    private final LruCache<String, Bitmap> memory = new LruCache<String, Bitmap>(
            Math.max(8 * 1024, (int) (Runtime.getRuntime().maxMemory() / 1024L / 16L))
    ) {
        @Override
        protected int sizeOf(String key, Bitmap bitmap) {
            return bitmap.getByteCount() / 1024;
        }
    };

    private ArtworkCache(Context context) {
        this.context = context.getApplicationContext();
        directory = new File(this.context.getFilesDir(), "album-artwork");
        if (!directory.exists()) directory.mkdirs();
    }

    public static ArtworkCache get(Context context) {
        if (instance == null) {
            synchronized (ArtworkCache.class) {
                if (instance == null) instance = new ArtworkCache(context);
            }
        }
        return instance;
    }

    public void load(LocalTrack track, Callback callback) {
        String key = keyFor(track);
        Bitmap cached = memory.get(key);
        if (cached != null) {
            callback.onArtwork(key, cached);
            return;
        }
        visibleExecutor.execute(() -> {
            prepare(track, false);
            Bitmap bitmap = readCachedBitmap(key);
            mainHandler.post(() -> callback.onArtwork(key, bitmap));
        });
    }

    /** Called synchronously by WorkManager, never from the main thread. */
    public synchronized int prepare(LocalTrack track, boolean retryMissing) {
        String key = keyFor(track);
        File image = imageFile(key);
        File missing = missingFile(key);
        if (image.isFile()) return RESULT_CACHED;
        if (missing.isFile() && !retryMissing) return RESULT_MISSING;
        if (retryMissing && missing.isFile()) missing.delete();

        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try (ParcelFileDescriptor descriptor = context.getContentResolver()
                .openFileDescriptor(Uri.parse(track.documentUri), "r")) {
            if (descriptor == null) return RESULT_ERROR;
            retriever.setDataSource(descriptor.getFileDescriptor());
            byte[] embedded = retriever.getEmbeddedPicture();
            if (embedded == null || embedded.length == 0) {
                createMarker(missing);
                return RESULT_MISSING;
            }
            Bitmap bitmap = decodeArtwork(embedded);
            if (bitmap == null) {
                createMarker(missing);
                return RESULT_MISSING;
            }
            File temporary = new File(directory, key + ".tmp");
            try (FileOutputStream output = new FileOutputStream(temporary)) {
                if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 88, output)) {
                    temporary.delete();
                    return RESULT_ERROR;
                }
            }
            if (image.exists()) image.delete();
            if (!temporary.renameTo(image)) {
                temporary.delete();
                return RESULT_ERROR;
            }
            missing.delete();
            memory.put(key, bitmap);
            return RESULT_FOUND;
        } catch (Exception ignored) {
            // I/O failures are intentionally not marked as "no cover" so a later
            // attempt can recover after a provider or permission becomes available.
            return RESULT_ERROR;
        } finally {
            try {
                retriever.release();
            } catch (Exception ignored) {
                // Some vendor retrievers throw for malformed files.
            }
        }
    }

    public String keyFor(LocalTrack track) {
        String album = clean(track.album);
        String identity;
        if (!album.isEmpty()) {
            String albumArtist = clean(track.albumArtist);
            if (albumArtist.isEmpty()) albumArtist = clean(track.artist);
            identity = "album\u001f" + albumArtist + "\u001f" + album;
        } else {
            identity = "track\u001f" + track.id + "\u001f" + track.modifiedAt;
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    identity.getBytes(StandardCharsets.UTF_8)
            );
            StringBuilder result = new StringBuilder(digest.length * 2);
            for (byte value : digest) result.append(String.format(Locale.ROOT, "%02x", value));
            return result.toString();
        } catch (Exception impossible) {
            return Integer.toHexString(identity.hashCode());
        }
    }

    public int cachedImageCount() {
        File[] files = directory.listFiles((dir, name) -> name.endsWith(".jpg"));
        return files == null ? 0 : files.length;
    }

    private Bitmap readCachedBitmap(String key) {
        Bitmap cached = memory.get(key);
        if (cached != null) return cached;
        Bitmap decoded = BitmapFactory.decodeFile(imageFile(key).getAbsolutePath());
        if (decoded != null) memory.put(key, decoded);
        return decoded;
    }

    private Bitmap decodeArtwork(byte[] data) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(data, 0, data.length, bounds);
        int sample = 1;
        while (bounds.outWidth / sample > MAX_ARTWORK_EDGE * 2
                || bounds.outHeight / sample > MAX_ARTWORK_EDGE * 2) {
            sample *= 2;
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = sample;
        Bitmap decoded = BitmapFactory.decodeByteArray(data, 0, data.length, options);
        if (decoded == null) return null;
        int width = decoded.getWidth();
        int height = decoded.getHeight();
        float scale = Math.min(1f, MAX_ARTWORK_EDGE / (float) Math.max(width, height));
        if (scale >= 1f) return decoded;
        Bitmap scaled = Bitmap.createScaledBitmap(
                decoded, Math.max(1, Math.round(width * scale)),
                Math.max(1, Math.round(height * scale)), true
        );
        if (scaled != decoded) decoded.recycle();
        return scaled;
    }

    private File imageFile(String key) {
        return new File(directory, key + ".jpg");
    }

    private File missingFile(String key) {
        return new File(directory, key + ".none");
    }

    private static void createMarker(File file) {
        try {
            file.createNewFile();
        } catch (Exception ignored) {
        }
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }
}
