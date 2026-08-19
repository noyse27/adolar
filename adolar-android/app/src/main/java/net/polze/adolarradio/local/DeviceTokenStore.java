package net.polze.adolarradio.local;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.io.IOException;
import java.security.GeneralSecurityException;

/** Keystore-backed storage for the Android mobile-sync device token. */
public final class DeviceTokenStore {
    private static final String TAG = "DeviceTokenStore";
    private static final String FILE_NAME = "adolar_device_token";
    private static final String KEY_TOKEN = "device_token";

    private DeviceTokenStore() {
    }

    private static SharedPreferences open(Context context) {
        try {
            MasterKey masterKey = new MasterKey.Builder(context)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            return EncryptedSharedPreferences.create(
                    context, FILE_NAME, masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            );
        } catch (GeneralSecurityException | IOException error) {
            // A device token is a convenience for background sync, not a
            // capability the app cannot function without: fall back to a
            // plain, non-encrypted store rather than crashing.
            Log.w(TAG, "Falling back to unencrypted device token storage", error);
            return context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE);
        }
    }

    public static String get(Context context) {
        return open(context).getString(KEY_TOKEN, null);
    }

    public static void set(Context context, String token) {
        open(context).edit().putString(KEY_TOKEN, token).apply();
    }

    public static void clear(Context context) {
        open(context).edit().remove(KEY_TOKEN).apply();
    }
}
