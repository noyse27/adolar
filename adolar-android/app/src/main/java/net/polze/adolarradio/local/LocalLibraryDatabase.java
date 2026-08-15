package net.polze.adolarradio.local;

import android.content.Context;

import androidx.room.Database;
import androidx.room.Room;
import androidx.room.RoomDatabase;

@Database(
        entities = {LibraryRoot.class, LocalTrack.class, TrackState.class},
        version = 1,
        exportSchema = true
)
public abstract class LocalLibraryDatabase extends RoomDatabase {
    private static volatile LocalLibraryDatabase instance;

    public abstract LibraryDao libraryDao();

    public static LocalLibraryDatabase get(Context context) {
        if (instance == null) {
            synchronized (LocalLibraryDatabase.class) {
                if (instance == null) {
                    instance = Room.databaseBuilder(
                            context.getApplicationContext(),
                            LocalLibraryDatabase.class,
                            "adolar-next-library.db"
                    ).build();
                }
            }
        }
        return instance;
    }
}
