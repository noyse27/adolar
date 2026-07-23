# Adolar Radio Android

Android companion app for Adolar Radio.

It has two surfaces backed by one player:

- Phone app: native station picker and playback controls connected to the app's media service.
- Android Auto: exposes a media service named "Adolar Radio" that uses Adolar's session-aware Smart Shuffle via `/api/random` and streams tracks from `/api/stream/<id>`.

The phone app and Android Auto control the same MediaSession. Playback never lives in a WebView, so locking the phone or leaving the phone UI does not create a second player or interrupt track advancement. Android Auto does not allow arbitrary browser/WebView UIs in the car; music apps must expose a media session/browser service instead.

## Build and install without Play Store

1. Install Android Studio.
2. Open this folder as a project: `adolar-android`.
3. Let Android Studio sync Gradle dependencies.
4. On your phone, enable developer options:
   - Android settings -> About phone -> tap "Build number" 7 times.
   - Developer options -> enable "USB debugging".
5. Connect the phone by USB and press **Run** in Android Studio.
6. Open **Adolar Radio** on the phone and enter your server URL, for example:

   ```text
   http://192.168.1.100:15002
   ```

## Android Auto developer test

1. Open Android Auto settings on the phone.
2. Tap the Android Auto version repeatedly until developer settings are enabled.
3. In Android Auto developer settings, enable **Unknown sources**.
4. Start Android Auto. The app should appear as a media app named **Adolar Radio**.

## Notes

- The installed app version is shown in both the native player header and the settings screen.
- The Android Auto media service supports Smart Shuffle playback, play/pause, previous/restart, and next. Its shuffle session survives media-service restarts and resets when the Adolar server URL changes.
- Playback runs as a foreground media service with a MediaStyle notification, wake lock, audio-focus handling, and automatic continuation after a completed track. This keeps playback alive when the phone UI is in the background or Android Auto disconnects from the app screen.
- Android Auto playback uses the public Adolar radio endpoints, so it does not need a login cookie.
- Cleartext HTTP is enabled because Adolar is commonly used on a local NAS URL.
