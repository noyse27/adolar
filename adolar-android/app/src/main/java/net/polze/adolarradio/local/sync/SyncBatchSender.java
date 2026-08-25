package net.polze.adolarradio.local.sync;

import net.polze.adolarradio.local.SyncOutboxEntry;

import java.util.List;
import java.util.Map;

/**
 * Sends a batch of outbox entries somewhere and reports back a per-event
 * outcome. {@link FakeLocalSyncBatchSender} is the only implementation until
 * the real Adolar mobile backend endpoint exists (Priority 2).
 */
public interface SyncBatchSender {
    Map<String, SyncBatchResult> sendBatch(List<SyncOutboxEntry> batch);
}
