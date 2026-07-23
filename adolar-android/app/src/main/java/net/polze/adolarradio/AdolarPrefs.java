package net.polze.adolarradio;

import android.content.Context;
import android.content.SharedPreferences;

final class AdolarPrefs {
    private static final String PREFS_NAME = "adolar_radio";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_SHUFFLE_SESSION = "shuffle_session_";
    private static final String KEY_STATION_ID = "station_id";

    private AdolarPrefs() {
    }

    static String getServerUrl(Context context) {
        return prefs(context).getString(KEY_SERVER_URL, "");
    }

    static void setServerUrl(Context context, String url) {
        String normalized = normalizeUrl(url);
        SharedPreferences preferences = prefs(context);
        SharedPreferences.Editor editor = preferences.edit().putString(KEY_SERVER_URL, normalized);
        if (!normalized.equals(preferences.getString(KEY_SERVER_URL, ""))) {
            editor.remove(KEY_STATION_ID);
            for (String key : preferences.getAll().keySet()) {
                if (key.startsWith(KEY_SHUFFLE_SESSION)) {
                    editor.remove(key);
                }
            }
        }
        editor.apply();
    }

    static String getShuffleSession(Context context, int stationId) {
        return prefs(context).getString(KEY_SHUFFLE_SESSION + stationId, "");
    }

    static void setShuffleSession(Context context, int stationId, String session) {
        prefs(context).edit()
                .putString(KEY_SHUFFLE_SESSION + stationId, session == null ? "" : session)
                .apply();
    }

    static int getStationId(Context context) {
        return prefs(context).getInt(KEY_STATION_ID, 1);
    }

    static void setStationId(Context context, int stationId) {
        prefs(context).edit().putInt(KEY_STATION_ID, stationId).apply();
    }

    static boolean hasServerUrl(Context context) {
        return !getServerUrl(context).isEmpty();
    }

    static String normalizeUrl(String raw) {
        String url = raw == null ? "" : raw.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    static boolean isValidServerUrl(String raw) {
        String url = normalizeUrl(raw);
        return url.startsWith("http://") || url.startsWith("https://");
    }

    static String radioUrl(Context context) {
        return getServerUrl(context) + "/radio";
    }

    static String apiUrl(Context context) {
        return getServerUrl(context);
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }
}
