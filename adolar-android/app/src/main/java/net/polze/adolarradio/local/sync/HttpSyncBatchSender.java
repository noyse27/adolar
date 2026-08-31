package net.polze.adolarradio.local.sync;

import android.content.Context;
import android.content.SharedPreferences;

import net.polze.adolarradio.local.DeviceTokenStore;
import net.polze.adolarradio.local.SyncOutboxEntry;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Real backend sender for {@code /api/android/v1/events/batch}, replacing
 * {@link FakeLocalSyncBatchSender} once a server URL and device token are
 * available. Deliberately does not reuse AdolarMediaService's private
 * connection helper -- this class stays self-contained so the sync package
 * has no dependency on the service package.
 */
public final class HttpSyncBatchSender implements SyncBatchSender {
    // Mirrors AdolarPrefs' package-private storage; that class cannot be
    // referenced from this package, so the same two constants are read here.
    private static final String PREFS_NAME = "adolar_radio";
    private static final String KEY_SERVER_URL = "server_url";

    private final Context context;

    public HttpSyncBatchSender(Context context) {
        this.context = context.getApplicationContext();
    }

    @Override
    public Map<String, SyncBatchResult> sendBatch(List<SyncOutboxEntry> batch) {
        String serverUrl = readServerUrl();
        String deviceToken = DeviceTokenStore.get(context);
        if (serverUrl.isEmpty() || deviceToken == null || deviceToken.isEmpty()) {
            throw new IllegalStateException(
                    "No server URL or device token available yet for sync.");
        }

        JSONArray events = new JSONArray();
        for (SyncOutboxEntry entry : batch) {
            try {
                JSONObject event = new JSONObject(entry.payloadJson);
                event.put("event_id", entry.eventId);
                events.put(event);
            } catch (Exception ignored) {
                // A malformed stored payload can never succeed; skip it here
                // and let the per-event fallback below mark it permanently failed.
            }
        }
        JSONObject body = new JSONObject();
        try {
            body.put("events", events);
        } catch (Exception ignored) {
            // JSONObject.put only throws for NaN/Infinite doubles, never here.
        }

        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(
                    serverUrl + "/api/android/v1/events/batch"
            ).openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Authorization", "Bearer " + deviceToken);
            try (OutputStream out = connection.getOutputStream()) {
                out.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            if (status == 401 || status == 403) {
                // The device token is gone/revoked; nothing in this batch can
                // succeed until it's replaced, but the caller's own retry/
                // backoff handles that -- just report every entry as failed.
                return retryableResultFor(batch);
            }
            InputStream stream = status >= 200 && status < 300
                    ? connection.getInputStream() : connection.getErrorStream();
            String responseBody = readAll(stream);
            Map<String, SyncBatchResult> results = parseResults(responseBody);
            if (status >= 400 && status < 500) {
                fillMissingWith(batch, results, SyncBatchResult.PERMANENT_ERROR);
            } else {
                fillMissingWith(batch, results, SyncBatchResult.RETRYABLE_ERROR);
            }
            return results;
        } catch (Exception error) {
            return retryableResultFor(batch);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private String readServerUrl() {
        SharedPreferences preferences =
                context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String url = preferences.getString(KEY_SERVER_URL, "");
        return url == null ? "" : url;
    }

    private static Map<String, SyncBatchResult> parseResults(String responseBody) {
        Map<String, SyncBatchResult> results = new LinkedHashMap<>();
        try {
            JSONObject parsed = new JSONObject(responseBody);
            JSONArray items = parsed.optJSONArray("results");
            if (items == null) return results;
            for (int index = 0; index < items.length(); index++) {
                JSONObject item = items.getJSONObject(index);
                String eventId = item.optString("event_id", null);
                if (eventId == null) continue;
                results.put(eventId, mapStatus(item.optString("status", "")));
            }
        } catch (Exception ignored) {
            // Falls through to an empty map; the caller fills every entry as failed.
        }
        return results;
    }

    private static SyncBatchResult mapStatus(String status) {
        switch (status) {
            case "applied": return SyncBatchResult.APPLIED;
            case "duplicate": return SyncBatchResult.DUPLICATE;
            case "unmatched": return SyncBatchResult.UNMATCHED;
            case "ambiguous": return SyncBatchResult.AMBIGUOUS;
            default: return SyncBatchResult.RETRYABLE_ERROR;
        }
    }

    private static void fillMissingWith(
            List<SyncOutboxEntry> batch, Map<String, SyncBatchResult> results,
            SyncBatchResult fallback
    ) {
        for (SyncOutboxEntry entry : batch) {
            if (!results.containsKey(entry.eventId)) {
                results.put(entry.eventId, fallback);
            }
        }
    }

    private static Map<String, SyncBatchResult> retryableResultFor(List<SyncOutboxEntry> batch) {
        Map<String, SyncBatchResult> results = new LinkedHashMap<>();
        for (SyncOutboxEntry entry : batch) {
            results.put(entry.eventId, SyncBatchResult.RETRYABLE_ERROR);
        }
        return results;
    }

    private static String readAll(InputStream stream) throws Exception {
        if (stream == null) return "";
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
        }
        return builder.toString();
    }
}
