# Playback-Refactoring: Umsetzungsstand

Stand: 11. August 2026

Dieses Handoff dokumentiert die abgearbeitete Playback-Roadmap für Web, Stream-
API und Android. Die ursprüngliche Analyse lag nur auf
`codex/playback-refactor-plan`; die Implementierung befindet sich nun auf dem
aktuellen Entwicklungszweig.

## Erledigt

### Phase 1: Messbarkeit

- Der Webplayer führt einen begrenzten Ringpuffer unter
  `window.__adolarPlaybackMetrics` und protokolliert Preload, Media-Events,
  gepufferte Sekunden, `play()`-Auflösung, Handoff und Queue-Latenz.
- Android protokolliert Batch-API-Latenz, Preload-Status, Buffering/Ready,
  Rebuffer-Dauer und Beginn/Ende des Crossfades über Logcat.
- Das Backend protokolliert Queue-Latenz, Streamstatus, Range, erstes Byte,
  Antwortdauer und gleichzeitig aktive Streamantworten.

### Phase 2: Browser

- `audio` und `audio-b` sind gleichwertige Slots mit einer veränderlichen
  Referenz auf den aktiven Slot.
- Ein erfolgreicher Crossfade tauscht nur die Rollen. URL, Decoder, Position und
  Netzwerkpuffer des eingehenden Slots bleiben erhalten.
- Radio-Refill läuft im Hintergrund und wird nur bei einer tatsächlich leeren
  Queue abgewartet. Ein einzelnes Promise verhindert parallele Refills.
- Der nächste feststehende Track wird sofort anhand seiner Track-ID vorgeladen.
  Veraltete Slots werden verworfen.
- Ein Fade startet nur mit mindestens elf gepufferten Sekunden; andernfalls
  bleibt der ausgehende Titel unverändert laut und der normale Endwechsel greift.
- Eventhandler sind an beide Slots gebunden und ignorieren Ereignisse eines
  gerade inaktiven Slots.

### Phase 3: Stream-API und Android-Cache

- Trackantworten enthalten `stream_version`; alle Player verwenden
  `/api/stream/<id>?v=<mtime_us>-<size>`.
- Voll- und Range-Antworten liefern konsistente `ETag`, `Last-Modified`,
  `Accept-Ranges`, `Cache-Control`, `Content-Length` und `Content-Range`-Header.
  Nur eine zur aktuellen Datei passende versionierte URL ist langfristig
  `immutable`; unversionierte oder veraltete URLs müssen revalidieren.
- Conditional GET (`If-None-Match`) und `If-Range` werden unterstützt.
- Android wurde von Media3 1.4.1 auf 1.9.4 aktualisiert.
- Ein gemeinsamer Media3-`SimpleCache` mit 384 MB LRU und versionierten
  Cache-Keys versorgt beide Android-Player.
- Android lädt fünf Trackmetadaten pro Anfrage in eine lokale Queue. Der zweite
  ExoPlayer übernimmt zugleich die kontrollierte Preload-Funktion; ein separater
  `DefaultPreloadManager` würde hier eine redundante dritte Pipeline erzeugen.
- Nginx/`X-Accel-Redirect` bleibt optional. Die deterministischen Pausen wurden
  ohne zusätzliche Deployment-Komponente beseitigt.

### Phase 4: Echter Android-Crossfade

- Zwei ExoPlayer teilen Cache und DataSource. Nur der aktive Player verwaltet
  Audiofokus und die einzige MediaSession.
- Acht Sekunden vor Trackende startet der vorbereitete Player bei Lautstärke
  null. Beide Lautstärken folgen einer Equal-Power-Kurve.
- Nach dem Fade werden die Playerrollen atomar getauscht und der alte Player als
  nächster Preload-Slot wiederverwendet.
- Pause, manueller Next, Audiofokusverlust und Preload-Fehler brechen einen Fade
  kontrolliert ab. WakeLock, Benachrichtigung und Telemetrie bleiben zentral im
  Service.

## Automatisch verifiziert

- JavaScript-Syntaxprüfung mit `node --check`.
- Python-Suite: 604 Tests plus Subtests; zusätzliche Regressionstests prüfen
  atomaren Web-Handoff, nicht blockierenden Refill, HTTP-Cache/Range-Semantik
  und die Android-Quellarchitektur.
- Android `:app:assembleDebug` erfolgreich; die Debug-APK liegt unter
  `adolar-android/app/build/outputs/apk/debug/app-debug.apk`.
- Android `:app:lintDebug` erfolgreich (verbleibende Java-8-Hinweise stammen
  aus der bestehenden Toolchain-Konfiguration).
- Android 0.5.0 (Version-Code 14) wurde per `adb install -r` auf einem
  Pixel 10 Pro XL installiert; Kaltstart, Prozess und Media-Service-Heartbeat
  wurden ohne Absturz verifiziert, vorhandene App-Daten blieben erhalten.
- Die öffentliche `/radio`-Oberfläche wurde im Browser geladen: zwei Audioslots,
  versionierte Stream-URL und atomarer Handoff sind im ausgelieferten Skript
  vorhanden; keine Browserfehler wurden protokolliert.

## Noch auf echter Hardware abzunehmen

Diese Punkte benötigen reale Audiodateien, Netzwerk und ein Android-Gerät und
sind keine offenen Implementierungsphasen:

- je 20 automatische Web-Radio- und Bibliothekswechsel;
- MP3, FLAC, M4A, OGG/Opus und AAC, soweit vorhanden;
- Hintergrundtab, manuelles Next und Senderwechsel während Preload/Fade;
- Android mit Display an/aus, Bluetooth und Android Auto;
- langsames/kurz unterbrochenes WLAN und nachgewiesener Cache-Hit;
- Zielwerte: gapless P95 unter 100 ms beziehungsweise keine unbeabsichtigte
  Stille im Crossfade-Modus.

Die Messdaten dafür stehen im Browser unter `window.__adolarPlaybackMetrics`
und auf Android in Logcat unter dem Tag `AdolarMediaService` bereit.
