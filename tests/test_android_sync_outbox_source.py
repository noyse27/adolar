from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "adolar-android"
LOCAL = "app/src/main/java/net/polze/adolarradio/local"


def read(relative: str) -> str:
    return (ANDROID / relative).read_text(encoding="utf-8")


def test_database_gets_a_non_destructive_migration_to_schema_three():
    database = read(f"{LOCAL}/LocalLibraryDatabase.java")
    assert "version = 3" in database
    assert "MIGRATION_2_3" in database
    assert ".addMigrations(MIGRATION_1_2, MIGRATION_2_3)" in database
    assert "fallbackToDestructiveMigration" not in database
    assert "SyncOutboxEntry.class" in database
    assert "SyncReceipt.class" in database
    assert "CREATE TABLE IF NOT EXISTS `sync_outbox`" in database
    assert "CREATE TABLE IF NOT EXISTS `sync_receipts`" in database


def test_sync_outbox_entry_has_the_fields_an_offline_queue_needs():
    entry = read(f"{LOCAL}/SyncOutboxEntry.java")
    assert 'tableName = "sync_outbox"' in entry
    assert "public String eventId" in entry
    assert "public String kind" in entry
    assert "public Long localTrackId" in entry
    assert "public String payloadJson" in entry
    assert "public long startedAtUtc" in entry
    assert "public String state" in entry
    assert "public int attempts" in entry
    assert "public Long nextRetryAt" in entry
    assert 'STATE_PENDING = "pending"' in entry
    assert 'STATE_SENDING = "sending"' in entry
    assert 'STATE_CONFIRMED = "confirmed"' in entry
    assert 'STATE_PERMANENT_ERROR = "permanent_error"' in entry


def test_sync_receipt_records_confirmed_events_for_compaction():
    receipt = read(f"{LOCAL}/SyncReceipt.java")
    assert 'tableName = "sync_receipts"' in receipt
    assert "public String eventId" in receipt
    assert "public long confirmedAt" in receipt


def test_dao_writes_playcount_and_outbox_entry_atomically():
    dao = read(f"{LOCAL}/LibraryDao.java")
    assert "@Transaction" in dao
    assert "recordLocalListeningOutcome" in dao
    assert "insertOutboxEntry" in dao
    assert "getSendableOutboxEntries" in dao
    assert "markOutboxSending" in dao
    assert "confirmOutboxEntry" in dao
    assert "markOutboxFailed" in dao
    assert "countPendingOutbox" in dao
    transaction_block = dao.split("default void recordLocalListeningOutcome", 1)[1]
    transaction_block = transaction_block.split("getSendableOutboxEntries", 1)[0]
    assert "recordCompletedPlay" in transaction_block
    assert "insertOutboxEntry" in transaction_block


def test_sync_batch_sender_seam_and_fake_implementation():
    sender = read(f"{LOCAL}/sync/SyncBatchSender.java")
    result = read(f"{LOCAL}/sync/SyncBatchResult.java")
    fake = read(f"{LOCAL}/sync/FakeLocalSyncBatchSender.java")
    assert "interface SyncBatchSender" in sender
    assert "sendBatch(List<SyncOutboxEntry> batch)" in sender
    for outcome in ("APPLIED", "DUPLICATE", "UNMATCHED", "AMBIGUOUS",
                     "PERMANENT_ERROR", "RETRYABLE_ERROR"):
        assert outcome in result
    assert "implements SyncBatchSender" in fake
    assert "SyncBatchResult.APPLIED" in fake


def test_sync_outbox_worker_follows_the_artwork_worker_pattern():
    worker = read(f"{LOCAL}/sync/SyncOutboxWorker.java")
    assert "extends Worker" in worker
    assert 'UNIQUE_WORK = "adolar-sync-outbox"' in worker
    assert "enqueueUniqueWork(" in worker
    assert "ExistingWorkPolicy.KEEP" in worker
    assert "PeriodicWorkRequest" in worker
    assert "NetworkType.CONNECTED" in worker
    assert "ExistingPeriodicWorkPolicy.KEEP" in worker
    assert "SyncBatchSender" in worker
    assert "Result.retry()" in worker


def test_gradle_already_has_workmanager():
    gradle = read("app/build.gradle")
    assert "androidx.work:work-runtime" in gradle


def test_local_playback_enqueues_started_skipped_and_completed_events():
    service = read("app/src/main/java/net/polze/adolarradio/AdolarMediaService.java")
    assert "enqueueLocalOutboxEvent" in service
    assert "updateLocalPlaybackEligibility" in service
    assert "localScrobbleEligible" in service
    assert "localEventId" in service
    assert "localStartedAtUtc" in service
    assert "SyncOutboxWorker.enqueue(this)" in service
    assert "SyncOutboxWorker.enqueuePeriodic(this)" in service

    start_track = service.split("private void startTrack(Track track, boolean playWhenReady", 1)[1]
    start_track = start_track.split("\n    }\n", 1)[0]
    assert 'enqueueLocalOutboxEvent(track, "started"' in start_track
    assert "startPositionMs == 0L" in start_track

    finish_track = service.split("private void finishCurrentTrack(", 1)[1]
    finish_track = finish_track.split("\n    }\n", 1)[0]
    assert "enqueueLocalOutboxEvent(" in finish_track
    assert "sendListeningEvent(" in finish_track

    outbox_event = service.split("private void enqueueLocalOutboxEvent(", 1)[1]
    outbox_event = outbox_event.split("\n    }\n", 1)[0]
    assert '"playcount_eligible"' in outbox_event
    assert '"scrobble_eligible"' in outbox_event
    assert '"started_at"' in outbox_event
    assert '"source", "android_local"' in outbox_event
    assert "recordLocalListeningOutcome" in outbox_event
