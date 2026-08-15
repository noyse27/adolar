package net.polze.adolarradio.local;

import androidx.room.Entity;
import androidx.room.ForeignKey;
import androidx.room.Index;
import androidx.room.PrimaryKey;

/** Personal state remains separate from rescannable file metadata. */
@Entity(
        tableName = "track_state",
        foreignKeys = @ForeignKey(
                entity = LocalTrack.class,
                parentColumns = "id",
                childColumns = "localTrackId",
                onDelete = ForeignKey.CASCADE
        ),
        indices = @Index("favorite")
)
public class TrackState {
    @PrimaryKey
    public long localTrackId;
    public int playCount;
    public Long lastPlayedAt;
    public boolean favorite;
}
