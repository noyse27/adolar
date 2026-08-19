package net.polze.adolarradio.local.sync;

import net.polze.adolarradio.local.SyncOutboxEntry;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Local stand-in for the real backend sender. Confirms every entry
 * immediately without any network call, so the outbox pipeline (write,
 * dequeue, confirm, compact) can be exercised end to end before the mobile
 * endpoint exists.
 */
public final class FakeLocalSyncBatchSender implements SyncBatchSender {
    @Override
    public Map<String, SyncBatchResult> sendBatch(List<SyncOutboxEntry> batch) {
        Map<String, SyncBatchResult> results = new LinkedHashMap<>();
        for (SyncOutboxEntry entry : batch) {
            results.put(entry.eventId, SyncBatchResult.APPLIED);
        }
        return results;
    }
}
