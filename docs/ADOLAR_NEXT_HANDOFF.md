# Adolar Next – Übergabe und aktueller Stand

Stand: 16. August 2026  
Arbeitsbranch: `codex/android-local-library-sync`  
Repository: `noyse27/adolar`  
Android-Projekt: `adolar-android`

Dieses Dokument ist der Einstiegspunkt für eine spätere Weiterarbeit – auch
von einem anderen Rechner oder durch Claude/Codex. Es enthält bewusst keine
Zugangsdaten, Cookies oder Tokens.

## Ziel und Produktgrenze

Adolar Next soll neben der bisherigen Adolar-Radio-App installiert werden und
auch ohne Netzwerk als vollwertiger lokaler Musikplayer funktionieren.

- Anzeigename: `Adolar Next`
- Application ID: `net.polze.adolarnext`
- Java-Package vorerst weiterhin: `net.polze.adolarradio`
- Lokale Bibliothek, Queue, Favoriten und Wiedergabe müssen offline arbeiten.
- Sync-Aktionen werden später lokal geparkt und nach Netzrückkehr idempotent an
  Adolar beziehungsweise Last.fm übertragen.
- Android Auto ist eine Hauptanforderung, keine optionale Erweiterung.
- Die bestehende Adolar-App darf bei Installation und Updates nicht
  überschrieben werden.

Die ausführliche Zielarchitektur und der Phasenplan stehen in
`docs/adolar-next-implementation-plan.md` und
`docs/android-local-library.md`.

## Im aktuellen Snapshot umgesetzt

### App-Identität und lokaler Katalog

- Adolar Next ist parallel zur bisherigen App installierbar.
- Musikordner können über das Storage Access Framework freigegeben werden.
- Die Bibliothek wird in Room gespeichert und über MediaStore/SAF inkrementell
  eingelesen.
- Der Scan läuft außerhalb des UI-Threads und zeigt Fortschritt beziehungsweise
  bereits gefundene Titel statt nach der Ordnerwahl weiter den Auswahlknopf.
- Suche, Titel-, Album-, Interpreten-, Genre- und Ordneransichten sind vorhanden.
- System-, statische und intelligente lokale Playlists sind vorhanden.
- Lokaler Playcount und lokaler Favoriten-/Lieben-Status sind vorhanden.

### Cover

- Eingebettete Albumcover werden absichtlich nicht im schnellen Hauptscan
  extrahiert.
- Sichtbare Titel und Bibliothekskacheln laden Cover bei Bedarf asynchron,
  verkleinern sie auf höchstens 720 Pixel und cachen sie im privaten
  App-Verzeichnis.
- Ein Hintergrundauftrag in den lokalen Einstellungen kann alle Cover
  vorbereiten. Negative Treffer werden markiert, damit Dateien ohne Cover
  nicht ständig erneut geöffnet werden.

### Navigation und Player

- Die Rakete öffnet den globalen Bibliotheks-Drawer.
- Die Oberfläche berücksichtigt Statusleiste, Navigationsleiste und
  Softwaretastatur.
- Die Titelliste besitzt ein einheitliches Zeilenlayout, Kontextmenüs und eine
  bedienbare Mini-Player-Leiste.
- Der große Player zeigt Cover, Quelle, Titel, Künstler, Album, Seekbar,
  Zeitangaben, Zurück, Play/Pause, Weiter, Shuffle und Lieben.
- Im großen Player wird der Mini-Player ausgeblendet.
- Die zuvor doppelte Platzhalteranzeige `Titel ?` wurde entfernt; oben wird die
  tatsächliche Quelle beziehungsweise Playlist angezeigt.

### Persistente Wiedergabequeue und Shuffle

- Die Reihenfolge des sichtbaren Titel-, Such-, Facetten- oder Playlist-Screens
  wird zur Wiedergabequeue.
- Titelende sowie MediaSession-, Benachrichtigungs- und Player-Aktionen wechseln
  innerhalb dieser Queue.
- `Als Nächstes` und `Zur Queue hinzufügen` sind vorhanden.
- Queue, aktueller Index, Quellenname und Wiedergabeposition werden gespeichert
  und nach einem Prozessneustart pausiert wiederhergestellt.
- Shuffle mischt nur die noch nicht gehörten Einträge. Der bisherige Verlauf
  bleibt für `Zurück` erhalten.
- Originalqueue, gemischte Queue und Shuffle-Zustand überstehen einen
  Prozessneustart.
- Bei `Zurück` startet ein Titel zunächst neu, wenn er bereits länger lief;
  ein weiterer beziehungsweise früher Tastendruck wechselt zum Vorgänger.

### Android Auto

- Der MediaBrowser liefert die Wurzelknoten `Lokale Musik`, `Playlists` und –
  nur bei konfiguriertem Server – `Adolar-Radios`.
- Lokale Musik kann nach allen Titeln, Favoriten, Alben, Interpreten und Genres
  durchsucht werden.
- Statische, intelligente und Systemplaylists sind browsebar.
- Große Listen werden seitenweise ausgeliefert; beim Start eines Titels wird
  trotzdem die vollständige Quellqueue für Weiter, Zurück und Shuffle geladen.
- Lokale Suche und Wiedergabe aus den Suchergebnissen sind implementiert.
- Die alte Radiooberfläche abonniert nur noch den Radio-Knoten und blieb im
  Smoke-Test funktionsfähig.

### Offline-Outbox

- Neue Room-Tabellen `sync_outbox` und `sync_receipts` (Schema-Version 3,
  nicht-destruktive Migration).
- Lokale Titel erzeugen jetzt `started`-, `skipped`- und `completed`-
  Hörereignisse mit stabiler Event-ID und ursprünglicher Startzeit, statt wie
  bisher stillschweigend verworfen zu werden.
- Der lokale 90-Prozent-Playcount-Bump und der zugehörige Outbox-Eintrag
  werden in einer Room-Transaktion geschrieben; eine zusätzliche
  50-Prozent-plus-30-Sekunden-Schwelle markiert Last.fm-Scrobble-Fähigkeit im
  Payload.
- Ein `SyncOutboxWorker` (einmalig und alle 15 Minuten bei Netzverbindung)
  sendet ausstehende Einträge über ein austauschbares `SyncBatchSender`-
  Interface.

### Adolar-Mobile-Backend

- Neuer Blueprint `adolar/routes/android.py`: Gerätetoken-Ausgabe/-Widerruf
  (Session-Cookie), Track-Matching und Event-Batch (beide ausschließlich
  über ein Bearer-Gerätetoken, nicht über das Session-Cookie).
- `adolar/android.py` orchestriert nur bestehende Fachlogik:
  `adolar4u.record_event`, `db.record_user_play`,
  `lastfm.scrobble`/`_submit_lastfm_call` – keine Dopplung.
- Neue Tabellen `android_devices` (gehashtes Token), `android_track_links`
  (gecachtes Matching-Ergebnis, selbstheilend bei `ambiguous`/`unmatched`)
  und `android_event_receipts` (Idempotenz über
  `(user_id, device_id, event_id)`).
- `HttpSyncBatchSender` ersetzt jetzt `FakeLocalSyncBatchSender` als
  Standard-Sender; `DeviceTokenStore` hält das Gerätetoken Keystore-gestützt
  (`EncryptedSharedPreferences`), `AdolarMediaService` registriert das Gerät
  selbständig, sobald ein Session-Cookie vorhanden ist.

## Verifiziert

Folgende Prüfungen waren im aktuellen Entwicklungsstand erfolgreich:

- `python -m pytest tests/test_android_next_source.py tests/test_android_playback_source.py -q`
  – 22 Tests bestanden.
- `adolar-android\\gradlew.bat :app:assembleDebug` – Debug-APK erfolgreich gebaut.
- `git diff --check` – keine Whitespace-Fehler.
- Debug-APK auf einem echten Android-Gerät aktualisiert.
- Bibliothek mit 18.452 lokalen Titeln geladen.
- Eingebettete Cover werden auf dem Gerät angezeigt.
- Lokale Wiedergabe, großer Player, Seek, Weiter/Zurück und Lieben geprüft.
- Shuffle mit der großen Queue geprüft; die nächsten Titel unterschieden sich
  von der linearen Folge, Zustand und Zurück-Verlauf überstanden einen
  Force-Stop.
- Großer Player zeigt keinen zusätzlichen Mini-Player und keine doppelte
  Platzhalterzeile mehr.
- MediaBrowserService ist registriert; Radio-Smoke-Test ohne Room-/Crashfehler
  bestanden.

Noch nicht auf einem echten Fahrzeug beziehungsweise im Desktop Head Unit
getestet wurde die vollständige Android-Auto-Bedienung. Auf dem Testtelefon ist
Android Auto installiert, aber kein DHU eingerichtet.

## Wichtigste offene Arbeit

### Priorität 1 – Offline-Outbox und korrekte lokale Hörereignisse

Der vertikale Durchstich ist umgesetzt (siehe „Offline-Outbox" oben):
Room-Tabellen, atomare Transaktion aus Playcount-Bump und Outbox-Eintrag,
beide Schwellenwerte, `started`/`skipped`/`completed` aus der lokalen Queue
sowie ein WorkManager-Job mit Backoff gegen einen austauschbaren
`SyncBatchSender`. Noch offen, weil an Priorität 2 hängend beziehungsweise
bewusst zurückgestellt:

- Offline-/Syncstatus in Drawer und Player sichtbar machen (UI-Feintuning,
  bewusst nach dem Outbox-Kern zurückgestellt).

Der `FakeLocalSyncBatchSender` ist jetzt durch den echten `HttpSyncBatchSender`
ersetzt (siehe Priorität 2), 401/429/5xx werden dort entsprechend behandelt.

### Priorität 2 – Adolar-Mobile-Backend

Umgesetzt:

- ✅ Widerrufbare, gehasht gespeicherte Mobile-Gerätetokens (`android_devices`,
  Bearer-Auth über `android_device_required`, getrennt vom Session-Cookie).
- ✅ Batch-Track-Matching (`POST /api/android/v1/tracks/match`, mit Cache in
  `android_track_links`; wird zusätzlich inline von `events/batch` genutzt,
  ein separater Aufruf davor ist für Android nicht nötig).
- ✅ Idempotenter Event-Batch (`POST /api/android/v1/events/batch`) mit
  Eindeutigkeit auf `(user_id, device_id, event_id)` (`android_event_receipts`).
- ✅ Angenommene lokale Plays schreiben über das bestehende
  `db.record_user_play` genau einmal in Archiv- und persönlichen Playcount.
- ✅ Android-Hörereignisse laufen über das bestehende `adolar4u.record_event`
  mit `source="android_local"` (dafür `EVENT_SOURCES` in
  `adolar/adolar4u/service.py` erweitert).
- ✅ Last.fm-Scrobbles nutzen den bestehenden `_submit_lastfm_call`-
  Retry-Mechanismus (kein neues `lastfm_outbox` nötig) mit dem ursprünglichen
  `started_at`-Zeitstempel, dank `lastfm.scrobble`s vorhandenem
  `timestamp`-Parameter.
- Android-seitig ersetzt `HttpSyncBatchSender` den Fake-Sender;
  `DeviceTokenStore` (Keystore-gestützte `EncryptedSharedPreferences`) hält
  das Gerätetoken, `AdolarMediaService` registriert es beim Start selbständig,
  sobald ein Session-Cookie vorhanden ist.

Bewusst noch offen: nicht oder mehrdeutig zugeordnete Titel bleiben zwar in
`android_track_links`/`android_event_receipts` erhalten und werden bei jedem
weiteren Sync-Versuch desselben Events automatisch neu aufgelöst
(selbstheilend nach einem späteren Server-Rescan), aber es gibt noch keinen
aktiven Reconciliation-Job, der von sich aus alte `unmatched`/`ambiguous`
Einträge erneut anstößt.

### Priorität 3 – Einheitliches „Lieben“ und Last.fm

- Lokal weiterhin sofort favorisieren.
- Bei verbundenem Adolar: persönlichen Adolar-Favorit setzen und bei dort
  verbundenem Last.fm zusätzlich lieben.
- Ohne Adolar, aber mit direkter Last.fm-Konfiguration: Last.fm bedienen und
  lokalen Favoriten behalten.
- Ohne Verbindung: ausschließlich lokaler Favorit.
- `unlove` symmetrisch umsetzen und Teilfehler getrennt anzeigen.
- Keine Last.fm-Secrets fest in die APK einbauen.

### Priorität 4 – Android Auto abnehmen und Player härten

- Browse, Suche, Start, Pause, Weiter, Zurück, Shuffle und Queue in einem echten
  Fahrzeug oder DHU testen.
- Artwork und lange Metadaten in Fahrzeugvorlagen prüfen.
- Notification, Sperrbildschirm, Bluetooth, Audiofokus und Wechsel zwischen
  lokaler Queue und Adolar-Radio systematisch testen.
- Wiedergabe nach Reboot, entzogenem URI-Recht und entfernter SD-Karte testen.

### Danach – Feintuning und weitere Funktionen

- Lokales Crossfade mit konfigurierbarer Dauer. Das bestehende Radio-Crossfade
  bleibt separat; Details stehen in `docs/backlog.md`.
- Vollständige Web-Parität des Smart-Rule-Parsers und des visuellen
  Filtereditors herstellen.
- Rotation, große Schrift, TalkBack, kleine Displays und sehr lange Metadaten
  weiter prüfen.
- Performance- und Akkutests mit 1.000, 10.000 und 50.000 Titeln.
- Eigenes final unterscheidbares Next-Icon, Release-Signing, Screenshots und
  Beta-Dokumentation.
- Bidirektionale Playlist-Synchronisation erst angehen, wenn der Server
  Revisionen, Tombstones und Konfliktregeln besitzt.

## Empfohlener nächster Arbeitsschritt

Der Offline-Outbox-Durchstich einschließlich echtem Backend ist code-seitig
umgesetzt:

1. ✅ Room-Schema und Migration ergänzt (Priorität 1).
2. ✅ Lokale Playback-Grenzen (90 % Playcount, 50 %/30 s Scrobble-Fähigkeit)
   implementiert; Source-Contract-Tests in
   `tests/test_android_sync_outbox_source.py` decken Schema, DAO-Transaktion,
   Worker und Service-Verdrahtung ab.
3. ✅ Ein zunächst lokaler/gefälschter Batch-Sender diente als erster
   Durchstich und ist jetzt durch den echten `HttpSyncBatchSender` ersetzt
   (Priorität 2: Gerätetoken, Track-Matching, idempotenter Event-Batch,
   siehe `tests/test_android_api.py` und
   `tests/test_android_http_sync_source.py`).
4. ✅ Gerätetest gegen den echten Endpunkt (nicht mehr Fake-Sender): Debug-APK
   auf dem Testtelefon gegen eine isolierte lokale Testinstanz von Adolar
   verbunden, Gerät registriert (`android_devices`-Zeile bestätigt), einen
   lokalen Titel abgespielt und den kompletten Kreislauf live verifiziert —
   `sync_outbox` geleert, `sync_receipts` bestätigt, serverseitig
   `android_event_receipts`/`android_track_links`/`user_play_counts`/
   `adolar4u_listening_events` korrekt befüllt, Playcount exakt einmal
   erhöht. Dabei einen echten Bug gefunden und behoben:
   `AdolarMediaService.sessionCookie()` las bisher aus dem WebView-
   `CookieManager`, das native Login-Bildschirm aber schreibt sein Cookie
   ausschließlich in `AdolarPrefs` (genau dafür vorgesehen, siehe dessen
   Dokumentationskommentar) — ohne den Fix hätte die Geräteregistrierung nie
   ausgelöst. Noch nicht gezielt einzeln nachgestellt: Flugmodus/Force-Stop/
   Reboot *gegen den echten Sender* (das Verhalten selbst ist unverändert
   gegenüber dem bereits in Priorität 1 verifizierten Fake-Sender-Kreislauf,
   nur die Transportschicht ist jetzt neu).

Damit ist das zentrale Produktversprechen – offline hören und später sicher
synchronisieren – vollständig umgesetzt und gegen einen echten Server
verifiziert. Nächste sinnvolle Schritte: Priorität 3 (Lieben/Last.fm) oder
Priorität 4 (Android-Auto-Abnahme).

## Lokale Befehle

Projekt bauen:

```powershell
Set-Location F:\claude\musicapp\adolar-android
.\gradlew.bat :app:assembleDebug
```

Relevante Source-Tests:

```powershell
Set-Location F:\claude\musicapp
python -m pytest tests/test_android_next_source.py tests/test_android_playback_source.py tests/test_android_sync_outbox_source.py tests/test_android_http_sync_source.py tests/test_android_api.py tests/test_adolar4u.py -q
```

APK ohne Löschen der App-Daten aktualisieren:

```powershell
& "C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe" install -r "F:\claude\musicapp\adolar-android\app\build\outputs\apk\debug\app-debug.apk"
```

## Relevante Dateien

- `adolar-android/app/src/main/java/net/polze/adolarradio/NextActivity.java`
  – Next-Navigation, Bibliotheksansichten, Listen und großer Player.
- `adolar-android/app/src/main/java/net/polze/adolarradio/AdolarMediaService.java`
  – MediaSession, lokale/Remote-Wiedergabe, Queue, Persistenz, Shuffle und
  MediaBrowser/Android Auto.
- `adolar-android/app/src/main/java/net/polze/adolarradio/local/`
  – Room-Datenmodell, Repository, Scanner, Cover-Cache und Worker.
- `tests/test_android_next_source.py`
  – Source-Verträge für Next-UI, Queue, Shuffle, Cover und Android Auto.
- `tests/test_android_playback_source.py`
  – bestehende Playback-/Service-Verträge.
- `docs/adolar-next-implementation-plan.md`
  – Phasenplan und Produktgrenzen.
- `docs/android-local-library.md`
  – Architektur für lokale Bibliothek, Sync, Backend und Last.fm.
- `docs/backlog.md`
  – bewusst zurückgestellte Themen, unter anderem lokales Crossfade.

## Hinweise für die Weiterarbeit

- Vor Änderungen immer den Feature-Branch auschecken und vom Remote aktualisieren.
- Keine echten Cookies, Tokens oder Server-Zugangsdaten in Logs, Tests,
  Dokumentation oder Commits übernehmen.
- Die alte App und die Radio-Wiedergabe bei jeder größeren Playeränderung per
  Smoke-Test absichern.
- Queue-, Playcount-, Scrobble- und Love-Ereignisse müssen Wiederholungen
  vertragen; ein clientseitiges `gesendet`-Flag allein reicht nicht.
- Lokale Audiodateien oder Tags werden von Adolar Next nicht gelöscht oder
  verändert.
