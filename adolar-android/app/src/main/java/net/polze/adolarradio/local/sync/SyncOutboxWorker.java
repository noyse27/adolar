package net.polze.adolarradio.local.sync;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import net.polze.adolarradio.local.LibraryDao;
import net.polze.adolarradio.local.LocalLibraryDatabase;
import net.polze.adolarradio.local.SyncOutboxEntry;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Drains {@code sync_outbox} through a {@link SyncBatchSender}. */
public final class SyncOutboxWorker extends Worker {
    public static final String UNIQUE_WORK = "adolar-sync-outbox";
    public static final String UNIQUE_PERIODIC_WORK = "adolar-sync-outbox-periodic";
    private static final int BATCH_SIZE = 50;
    private static final long INITIAL_BACKOFF_MS = 30_000L;

    public SyncOutboxWorker(@NonNull Context appContext, @NonNull WorkerParameters workerParams) {
        super(appContext, workerParams);
    }

    public static void enqueue(Context context) {
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(SyncOutboxWorker.class)
                .build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_WORK, ExistingWorkPolicy.KEEP, request
        );
    }

    public static void enqueuePeriodic(Context context) {
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                SyncOutboxWorker.class, 15, TimeUnit.MINUTES
        ).setConstraints(constraints).build();
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                UNIQUE_PERIODIC_WORK, ExistingPeriodicWorkPolicy.KEEP, request
        );
    }

    /** Swappable seam, currently wired to the real backend sender. */
    static SyncBatchSender createSender(Context context) {
        return new HttpSyncBatchSender(context);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        LibraryDao dao = LocalLibraryDatabase.get(context).libraryDao();
        long now = System.currentTimeMillis();
        List<SyncOutboxEntry> batch = dao.getSendableOutboxEntries(now, BATCH_SIZE);
        if (batch.isEmpty()) {
            return Result.success();
        }
        for (SyncOutboxEntry entry : batch) {
            dao.markOutboxSending(entry.eventId);
        }

        Map<String, SyncBatchResult> results;
        try {
            results = createSender(context).sendBatch(batch);
        } catch (Exception error) {
            for (SyncOutboxEntry entry : batch) {
                dao.markOutboxFailed(
                        entry.eventId, SyncOutboxEntry.STATE_PENDING,
                        String.valueOf(error.getMessage()), backoffAt(entry.attempts)
                );
            }
            return Result.retry();
        }

        for (SyncOutboxEntry entry : batch) {
            SyncBatchResult result = results.get(entry.eventId);
            if (result == SyncBatchResult.APPLIED || result == SyncBatchResult.DUPLICATE) {
                dao.confirmOutboxEntry(entry.eventId, System.currentTimeMillis());
            } else if (result == SyncBatchResult.PERMANENT_ERROR) {
                dao.markOutboxFailed(
                        entry.eventId, SyncOutboxEntry.STATE_PERMANENT_ERROR,
                        "permanent_error", null
                );
            } else {
                // UNMATCHED, AMBIGUOUS, RETRYABLE_ERROR, or a missing result all
                // retry later with backoff rather than being lost.
                dao.markOutboxFailed(
                        entry.eventId, SyncOutboxEntry.STATE_PENDING,
                        result == null ? "no_result" : result.name(), backoffAt(entry.attempts)
                );
            }
        }
        return Result.success();
    }

    private static long backoffAt(int attempts) {
        long delay = INITIAL_BACKOFF_MS << Math.min(attempts, 6);
        return System.currentTimeMillis() + delay;
    }
}
