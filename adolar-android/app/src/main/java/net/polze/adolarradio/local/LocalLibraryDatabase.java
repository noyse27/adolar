package net.polze.adolarradio.local;

import android.content.Context;

import androidx.room.Database;
import androidx.room.Room;
import androidx.room.RoomDatabase;
import androidx.annotation.NonNull;
import androidx.room.migration.Migration;
import androidx.sqlite.db.SupportSQLiteDatabase;

@Database(
        entities = {
                LibraryRoot.class,
                LocalTrack.class,
                TrackState.class,
                LocalPlaylist.class,
                PlaylistTrack.class
        },
        version = 2,
        exportSchema = true
)
public abstract class LocalLibraryDatabase extends RoomDatabase {
    private static volatile LocalLibraryDatabase instance;

    public static final Migration MIGRATION_1_2 = new Migration(1, 2) {
        @Override
        public void migrate(@NonNull SupportSQLiteDatabase database) {
            database.execSQL("CREATE TABLE IF NOT EXISTS `playlists` ("
                    + "`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "
                    + "`name` TEXT NOT NULL, `type` TEXT NOT NULL, "
                    + "`filterJson` TEXT NOT NULL, `sort` TEXT NOT NULL, "
                    + "`isSystem` INTEGER NOT NULL, `systemKey` TEXT, "
                    + "`createdAt` INTEGER NOT NULL, `updatedAt` INTEGER NOT NULL)");
            database.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS "
                    + "`index_playlists_systemKey` ON `playlists` (`systemKey`)");
            database.execSQL("CREATE INDEX IF NOT EXISTS `index_playlists_name` "
                    + "ON `playlists` (`name`)");
            database.execSQL("CREATE TABLE IF NOT EXISTS `playlist_tracks` ("
                    + "`playlistId` INTEGER NOT NULL, `localTrackId` INTEGER NOT NULL, "
                    + "`position` INTEGER NOT NULL, `addedAt` INTEGER NOT NULL, "
                    + "PRIMARY KEY(`playlistId`, `localTrackId`), "
                    + "FOREIGN KEY(`playlistId`) REFERENCES `playlists`(`id`) "
                    + "ON UPDATE NO ACTION ON DELETE CASCADE, "
                    + "FOREIGN KEY(`localTrackId`) REFERENCES `local_tracks`(`id`) "
                    + "ON UPDATE NO ACTION ON DELETE CASCADE)");
            database.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS "
                    + "`index_playlist_tracks_playlistId_position` "
                    + "ON `playlist_tracks` (`playlistId`, `position`)");
            database.execSQL("CREATE INDEX IF NOT EXISTS "
                    + "`index_playlist_tracks_localTrackId` "
                    + "ON `playlist_tracks` (`localTrackId`)");
            seedSystemPlaylists(database);
        }
    };

    public abstract LibraryDao libraryDao();

    public static LocalLibraryDatabase get(Context context) {
        if (instance == null) {
            synchronized (LocalLibraryDatabase.class) {
                if (instance == null) {
                    instance = Room.databaseBuilder(
                            context.getApplicationContext(),
                            LocalLibraryDatabase.class,
                            "adolar-next-library.db"
                    ).addMigrations(MIGRATION_1_2)
                            .addCallback(new Callback() {
                                @Override
                                public void onOpen(@NonNull SupportSQLiteDatabase database) {
                                    seedSystemPlaylists(database);
                                }
                            })
                            .build();
                }
            }
        }
        return instance;
    }

    private static void seedSystemPlaylists(SupportSQLiteDatabase database) {
        long now = System.currentTimeMillis();
        seed(database, "Favoriten", "favorites", now);
        seed(database, "Kürzlich hinzugefügt", "recently_added", now);
        seed(database, "Häufig gespielt", "most_played", now);
        seed(database, "Kürzlich gespielt", "recently_played", now);
        seed(database, "Selten gespielt", "least_played", now);
        seed(database, "Nie gespielt", "never_played", now);
    }

    private static void seed(
            SupportSQLiteDatabase database, String name, String key, long now
    ) {
        database.execSQL(
                "INSERT OR IGNORE INTO playlists "
                        + "(name,type,filterJson,sort,isSystem,systemKey,createdAt,updatedAt) "
                        + "VALUES (?, 'system', ?, 'artist', 1, ?, ?, ?)",
                new Object[]{name, "{\"system\":\"" + key + "\"}", key, now, now}
        );
    }
}
