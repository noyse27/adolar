package net.polze.adolarradio.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.Index;
import androidx.room.PrimaryKey;

@Entity(
        tableName = "playlists",
        indices = {
                @Index(value = {"systemKey"}, unique = true),
                @Index(value = {"name"})
        }
)
public class LocalPlaylist {
    @PrimaryKey(autoGenerate = true)
    public long id;
    @NonNull
    public String name = "";
    @NonNull
    public String type = "static";
    @NonNull
    public String filterJson = "{}";
    @NonNull
    public String sort = "artist";
    public boolean isSystem;
    public String systemKey;
    public long createdAt;
    public long updatedAt;
}
