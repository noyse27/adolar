package net.polze.adolarradio.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** Local proof that an outbox event was already confirmed, kept for compaction. */
@Entity(tableName = "sync_receipts")
public class SyncReceipt {
    @PrimaryKey
    @NonNull
    public String eventId = "";
    public long confirmedAt;
}
