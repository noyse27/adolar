package net.polze.adolarradio.local;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Update;

import java.util.List;

@Dao
public interface LibraryDao {
    @Query("SELECT * FROM library_roots ORDER BY addedAt")
    List<LibraryRoot> getRoots();

    @Query("SELECT * FROM library_roots WHERE treeUri=:treeUri LIMIT 1")
    LibraryRoot getRoot(String treeUri);

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    void saveRoot(LibraryRoot root);

    @Query("SELECT * FROM local_tracks WHERE missing=0 "
            + "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            + "COALESCE(trackNo, 2147483647), title COLLATE NOCASE")
    List<LocalTrack> getActiveTracks();

    @Query("SELECT * FROM local_tracks WHERE id=:id LIMIT 1")
    LocalTrack getTrack(long id);

    @Query("SELECT * FROM local_tracks WHERE documentUri=:documentUri LIMIT 1")
    LocalTrack getTrackByDocumentUri(String documentUri);

    @Insert
    long insertTrack(LocalTrack track);

    @Update
    void updateTrack(LocalTrack track);

    @Query("UPDATE local_tracks SET lastSeenScan=:scanId, indexedAt=:indexedAt, missing=0 "
            + "WHERE id=:trackId")
    void touchTrack(long trackId, long scanId, long indexedAt);

    @Query("UPDATE local_tracks SET missing=1 WHERE rootUri=:rootUri "
            + "AND lastSeenScan!=:scanId")
    int markUnseenMissing(String rootUri, long scanId);

    @Query("SELECT COUNT(*) FROM local_tracks WHERE missing=0")
    int activeTrackCount();
}
