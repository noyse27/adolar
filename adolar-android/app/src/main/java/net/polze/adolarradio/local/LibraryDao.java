package net.polze.adolarradio.local;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Update;
import androidx.room.Delete;

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

    @Query("SELECT * FROM local_tracks WHERE missing=0 "
            + "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            + "COALESCE(trackNo, 2147483647), title COLLATE NOCASE LIMIT :limit")
    List<LocalTrack> getActiveTrackPreview(int limit);

    @Query("SELECT album AS name, COUNT(*) AS trackCount FROM local_tracks "
            + "WHERE missing=0 AND album IS NOT NULL AND TRIM(album)!='' "
            + "GROUP BY album COLLATE NOCASE ORDER BY album COLLATE NOCASE")
    List<LibraryFacet> getAlbums();

    @Query("SELECT artist AS name, COUNT(*) AS trackCount FROM local_tracks "
            + "WHERE missing=0 AND artist IS NOT NULL AND TRIM(artist)!='' "
            + "GROUP BY artist COLLATE NOCASE ORDER BY artist COLLATE NOCASE")
    List<LibraryFacet> getArtists();

    @Query("SELECT genre AS name, COUNT(*) AS trackCount FROM local_tracks "
            + "WHERE missing=0 AND genre IS NOT NULL AND TRIM(genre)!='' "
            + "GROUP BY genre COLLATE NOCASE ORDER BY genre COLLATE NOCASE")
    List<LibraryFacet> getGenres();

    @Query("SELECT * FROM local_tracks WHERE missing=0 AND ("
            + "INSTR(LOWER(title), LOWER(:query))>0 OR "
            + "INSTR(LOWER(artist), LOWER(:query))>0 OR "
            + "INSTR(LOWER(album), LOWER(:query))>0 OR "
            + "INSTR(LOWER(genre), LOWER(:query))>0) "
            + "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            + "COALESCE(trackNo, 2147483647), title COLLATE NOCASE")
    List<LocalTrack> searchTracks(String query);

    @Query("SELECT * FROM local_tracks WHERE missing=0 AND album=:name COLLATE NOCASE "
            + "ORDER BY COALESCE(trackNo, 2147483647), title COLLATE NOCASE")
    List<LocalTrack> getTracksByAlbum(String name);

    @Query("SELECT * FROM local_tracks WHERE missing=0 AND artist=:name COLLATE NOCASE "
            + "ORDER BY album COLLATE NOCASE, COALESCE(trackNo, 2147483647), "
            + "title COLLATE NOCASE")
    List<LocalTrack> getTracksByArtist(String name);

    @Query("SELECT * FROM local_tracks WHERE missing=0 AND genre=:name COLLATE NOCASE "
            + "ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            + "COALESCE(trackNo, 2147483647), title COLLATE NOCASE")
    List<LocalTrack> getTracksByGenre(String name);

    @Query("SELECT * FROM local_tracks WHERE rootUri=:rootUri")
    List<LocalTrack> getTracksForRoot(String rootUri);

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

    @Query("SELECT * FROM playlists ORDER BY isSystem DESC, name COLLATE NOCASE")
    List<LocalPlaylist> getPlaylists();

    @Query("SELECT * FROM playlists WHERE id=:playlistId LIMIT 1")
    LocalPlaylist getPlaylist(long playlistId);

    @Insert
    long insertPlaylist(LocalPlaylist playlist);

    @Update
    void updatePlaylist(LocalPlaylist playlist);

    @Delete
    void deletePlaylist(LocalPlaylist playlist);

    @Query("SELECT t.* FROM playlist_tracks pt JOIN local_tracks t "
            + "ON t.id=pt.localTrackId WHERE pt.playlistId=:playlistId AND t.missing=0 "
            + "ORDER BY pt.position")
    List<LocalTrack> getStaticPlaylistTracks(long playlistId);

    @Query("SELECT COALESCE(MAX(position), -1) + 1 FROM playlist_tracks "
            + "WHERE playlistId=:playlistId")
    int nextPlaylistPosition(long playlistId);

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    long insertPlaylistTrack(PlaylistTrack playlistTrack);

    @Query("SELECT * FROM track_state")
    List<TrackState> getTrackStates();

    @Query("SELECT localTrackId FROM track_state WHERE favorite=1")
    List<Long> getFavoriteTrackIds();

    @Query("INSERT INTO track_state(localTrackId,playCount,lastPlayedAt,favorite) "
            + "VALUES(:trackId,0,NULL,:favorite) ON CONFLICT(localTrackId) DO UPDATE "
            + "SET favorite=:favorite")
    void setFavorite(long trackId, boolean favorite);

    @Query("INSERT INTO track_state(localTrackId,playCount,lastPlayedAt,favorite) "
            + "VALUES(:trackId,1,:playedAt,0) ON CONFLICT(localTrackId) DO UPDATE "
            + "SET playCount=playCount+1,lastPlayedAt=:playedAt")
    void recordCompletedPlay(long trackId, long playedAt);

    @Query("SELECT t.* FROM local_tracks t JOIN track_state s ON s.localTrackId=t.id "
            + "WHERE t.missing=0 AND s.favorite=1 "
            + "ORDER BY t.artist COLLATE NOCASE, t.title COLLATE NOCASE")
    List<LocalTrack> getFavoriteTracks();

    @Query("SELECT * FROM local_tracks WHERE missing=0 ORDER BY addedAt DESC LIMIT 500")
    List<LocalTrack> getRecentlyAddedTracks();

    @Query("SELECT t.* FROM local_tracks t JOIN track_state s ON s.localTrackId=t.id "
            + "WHERE t.missing=0 AND s.playCount>0 ORDER BY s.playCount DESC, "
            + "s.lastPlayedAt DESC LIMIT 500")
    List<LocalTrack> getMostPlayedTracks();

    @Query("SELECT t.* FROM local_tracks t JOIN track_state s ON s.localTrackId=t.id "
            + "WHERE t.missing=0 AND s.lastPlayedAt IS NOT NULL "
            + "ORDER BY s.lastPlayedAt DESC LIMIT 500")
    List<LocalTrack> getRecentlyPlayedTracks();

    @Query("SELECT t.* FROM local_tracks t JOIN track_state s ON s.localTrackId=t.id "
            + "WHERE t.missing=0 AND s.playCount>0 ORDER BY s.playCount ASC, "
            + "s.lastPlayedAt ASC LIMIT 500")
    List<LocalTrack> getLeastPlayedTracks();

    @Query("SELECT t.* FROM local_tracks t LEFT JOIN track_state s ON s.localTrackId=t.id "
            + "WHERE t.missing=0 AND COALESCE(s.playCount,0)=0 "
            + "ORDER BY t.artist COLLATE NOCASE, t.title COLLATE NOCASE LIMIT 500")
    List<LocalTrack> getNeverPlayedTracks();
}
