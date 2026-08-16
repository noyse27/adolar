package net.polze.adolarradio.local;

/** Album, artist, or genre aggregation returned directly by Room. */
public final class LibraryFacet {
    public String name;
    public int trackCount;
    public long artworkTrackId;
    public String artworkDocumentUri;
    public String artworkArtist;
    public String artworkAlbum;
    public String artworkAlbumArtist;
    public long artworkModifiedAt;

    public LocalTrack artworkTrack() {
        LocalTrack track = new LocalTrack();
        track.id = artworkTrackId;
        track.documentUri = artworkDocumentUri == null ? "" : artworkDocumentUri;
        track.artist = artworkArtist;
        track.album = artworkAlbum;
        track.albumArtist = artworkAlbumArtist;
        track.modifiedAt = artworkModifiedAt;
        return track;
    }
}
