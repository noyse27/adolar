package net.polze.adolarradio.local;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.work.Data;
import androidx.work.ExistingWorkPolicy;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Reliable user-triggered preparation of embedded album covers. */
public final class ArtworkPrefetchWorker extends Worker {
    public static final String UNIQUE_WORK = "adolar-local-artwork";
    public static final String PREFS = "local_artwork_status";
    public static final String STATUS = "status";
    public static final String PROCESSED = "processed";
    public static final String TOTAL = "total";
    public static final String FOUND = "found";
    public static final String ERRORS = "errors";
    private static final String RETRY_MISSING = "retry_missing";

    public ArtworkPrefetchWorker(
            @NonNull Context appContext, @NonNull WorkerParameters workerParams
    ) {
        super(appContext, workerParams);
    }

    public static void enqueue(Context context, boolean retryMissing) {
        Data input = new Data.Builder().putBoolean(RETRY_MISSING, retryMissing).build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(
                ArtworkPrefetchWorker.class
        ).setInputData(input).build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_WORK, ExistingWorkPolicy.KEEP, request
        );
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        ArtworkCache cache = ArtworkCache.get(context);
        List<LocalTrack> tracks = LocalLibraryDatabase.get(context)
                .libraryDao().getActiveTracks();
        Map<String, List<LocalTrack>> albums = new LinkedHashMap<>();
        for (LocalTrack track : tracks) {
            String albumKey = cache.keyFor(track);
            List<LocalTrack> candidates = albums.get(albumKey);
            if (candidates == null) {
                candidates = new ArrayList<>(3);
                albums.put(albumKey, candidates);
            }
            // A minority of collections embeds art only in some tracks. Trying a
            // few files keeps preparation reliable without opening every song.
            if (candidates.size() < 3) candidates.add(track);
        }

        SharedPreferences status = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int total = albums.size();
        int processed = 0;
        int found = 0;
        int errors = 0;
        writeStatus(status, "running", processed, total, found, errors);
        boolean retryMissing = getInputData().getBoolean(RETRY_MISSING, false);

        for (List<LocalTrack> candidates : albums.values()) {
            if (isStopped()) {
                writeStatus(status, "paused", processed, total, found, errors);
                return Result.retry();
            }
            int result = ArtworkCache.RESULT_MISSING;
            for (int index = 0; index < candidates.size(); index++) {
                result = cache.prepare(candidates.get(index), retryMissing || index > 0);
                if (result == ArtworkCache.RESULT_FOUND
                        || result == ArtworkCache.RESULT_CACHED) break;
            }
            processed++;
            if (result == ArtworkCache.RESULT_FOUND) found++;
            if (result == ArtworkCache.RESULT_ERROR) errors++;
            if (processed == 1 || processed % 10 == 0 || processed == total) {
                writeStatus(status, "running", processed, total, found, errors);
                setProgressAsync(new Data.Builder()
                        .putInt(PROCESSED, processed).putInt(TOTAL, total)
                        .putInt(FOUND, found).putInt(ERRORS, errors).build());
            }
        }
        writeStatus(status, "complete", processed, total, found, errors);
        return Result.success();
    }

    private static void writeStatus(
            SharedPreferences preferences, String state, int processed,
            int total, int found, int errors
    ) {
        preferences.edit()
                .putString(STATUS, state)
                .putInt(PROCESSED, processed)
                .putInt(TOTAL, total)
                .putInt(FOUND, found)
                .putInt(ERRORS, errors)
                .apply();
    }
}
