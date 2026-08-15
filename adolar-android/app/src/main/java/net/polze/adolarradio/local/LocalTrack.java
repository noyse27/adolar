package net.polze.adolarradio.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.Index;
import androidx.room.PrimaryKey;

/** Locally indexed metadata, deliberately shaped like Adolar's server track model. */
@Entity(
        tableName = "local_tracks",
        indices = {
                @Index(value = {"documentUri"}, unique = true),
                @Index(value = {"rootUri", "missing"}),
                @Index(value = {"artist", "album", "trackNo"}),
                @Index(value = {"title"}),
                @Index(value = {"genre"}),
                @Index(value = {"lastSeenScan"})
        }
)
public class LocalTrack {
    @PrimaryKey(autoGenerate = true)
    public long id;

    @NonNull
    public String rootUri = "";
    @NonNull
    public String documentUri = "";
    public String documentId;
    public String displayName;
    public String mimeType;
    public String title;
    public String artist;
    public String album;
    public String albumArtist;
    public String genre;
    public Integer year;
    public Integer trackNo;
    public long durationSeconds;
    public int bitrateKbps;
    public long sizeBytes;
    public long modifiedAt;
    public long addedAt;
    public long indexedAt;
    public long lastSeenScan;
    public boolean missing;
}
