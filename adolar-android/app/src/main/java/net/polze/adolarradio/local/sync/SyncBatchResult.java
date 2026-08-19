package net.polze.adolarradio.local.sync;

/**
 * Per-event outcome of a batch send, mirroring the response contract described
 * for the future {@code POST /api/android/v1/events/batch} endpoint (see
 * docs/android-local-library.md) so a real sender can replace
 * {@link FakeLocalSyncBatchSender} without any worker/DAO changes.
 */
public enum SyncBatchResult {
    APPLIED,
    DUPLICATE,
    UNMATCHED,
    AMBIGUOUS,
    PERMANENT_ERROR,
    RETRYABLE_ERROR
}
