package net.polze.adolarradio.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** A directory tree explicitly granted by the user through Android's SAF picker. */
@Entity(tableName = "library_roots")
public class LibraryRoot {
    @PrimaryKey
    @NonNull
    public String treeUri = "";
    public String displayName = "";
    public long addedAt;
    public Long lastScanAt;
    public String lastScanStatus = "pending";
    public String lastScanError;
}
