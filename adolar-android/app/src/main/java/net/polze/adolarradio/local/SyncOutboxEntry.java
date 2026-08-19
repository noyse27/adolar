package net.polze.adolarradio.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.Index;
import androidx.room.PrimaryKey;

/** Unsynced local action, written atomically with its local-state change. */
@Entity(
        tableName = "sync_outbox",
        indices = @Index(value = {"state", "nextRetryAt"})
)
public class SyncOutboxEntry {
    public static final String KIND_LISTENING_EVENT = "listening_event";
    public static final String KIND_FAVORITE_EVENT = "favorite_event";

    public static final String STATE_PENDING = "pending";
    public static final String STATE_SENDING = "sending";
    public static final String STATE_CONFIRMED = "confirmed";
    public static final String STATE_PERMANENT_ERROR = "permanent_error";

    @PrimaryKey
    @NonNull
    public String eventId = "";
    @NonNull
    public String kind = KIND_LISTENING_EVENT;
    public Long localTrackId;
    @NonNull
    public String payloadJson = "{}";
    public long createdAt;
    public long startedAtUtc;
    @NonNull
    public String state = STATE_PENDING;
    public int attempts;
    public String lastError;
    public Long nextRetryAt;
}
