package net.polze.adolarradio.local;

import androidx.room.Entity;
import androidx.room.ForeignKey;
import androidx.room.Index;

@Entity(
        tableName = "playlist_tracks",
        primaryKeys = {"playlistId", "localTrackId"},
        foreignKeys = {
                @ForeignKey(
                        entity = LocalPlaylist.class,
                        parentColumns = "id",
                        childColumns = "playlistId",
                        onDelete = ForeignKey.CASCADE
                ),
                @ForeignKey(
                        entity = LocalTrack.class,
                        parentColumns = "id",
                        childColumns = "localTrackId",
                        onDelete = ForeignKey.CASCADE
                )
        },
        indices = {
                @Index(value = {"playlistId", "position"}, unique = true),
                @Index(value = {"localTrackId"})
        }
)
public class PlaylistTrack {
    public long playlistId;
    public long localTrackId;
    public int position;
    public long addedAt;
}
