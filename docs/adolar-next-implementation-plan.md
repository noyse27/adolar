# Adolar Next – Umsetzungsplan

Stand: 15. August 2026
Branch: `codex/android-local-library-sync`
Zieldokument: `docs/android-local-library.md`

## Produktgrenze

Adolar Next ist eine neue, parallel installierbare Android-App. Sie ersetzt die
bisherige App nicht und übernimmt deren private Daten nicht automatisch.

| Eigenschaft | Bestehende App | Adolar Next |
| --- | --- | --- |
| Anzeigename | Adolar Radio | Adolar Next |
| Application ID | `net.polze.adolarradio` | `net.polze.adolarnext` |
| Datenbereich | eigener Android-Sandbox | eigener Android-Sandbox |
| Versionslinie | bisherige Versionen | beginnt bei `0.1.0-next` |
| Hauptzweck | Adolar-Radiostreams | Offline-Player plus Adolar-Verbindung |

Der interne Java-Namespace bleibt zunächst `net.polze.adolarradio`. Er ist für
die installierte Identität nicht relevant und vermeidet zu Beginn einen
risikoreichen Massenumbau. Eine spätere reine Namespace-Bereinigung liefert
keinen Produktnutzen und wird nur durchgeführt, wenn die neue Architektur
ohnehin die betroffenen Klassen ersetzt.

## Leitlinien

1. Lokale Wiedergabe funktioniert ohne Server-URL und ohne Netzwerk.
2. Room ist die maßgebliche Datenquelle der Android-Oberfläche.
3. Jede synchronisierbare Änderung wird zuerst lokal abgeschlossen.
4. Netzwerk-Sync ist wiederholbar und serverseitig idempotent.
5. Adolar-Radios existieren nur bei einer Adolar-Verbindung; sie sind keine
   lokalen Radiosender.
6. Die Rakete ist der globale Menüknopf und öffnet den Bibliotheks-Drawer.
7. Bestehende Radio-Wiedergabe bleibt während des Umbaus in jeder Phase
   funktionsfähig.
8. Android Auto ist eine Hauptanforderung: lokale Bibliothek, lokale
   Playlists, Queue und Adolar-Radios müssen im Fahrzeug ohne Bedienung des
   Handydisplays erreichbar und sicher steuerbar sein.

## Lieferstrategie

Die Entwicklung erfolgt in vertikalen, jeweils auf einem echten Gerät
abnehmbaren Scheiben. Keine Phase darf eine nur halb persistierte Bibliothek
oder nicht wiederholbaren Sync hinterlassen.

### Phase 0 – Eigenständige App-Identität

**Ergebnis:** Adolar Next kann neben Adolar Radio installiert und unabhängig
aktualisiert/deinstalliert werden.

- `applicationId` auf `net.polze.adolarnext` setzen;
- Anzeigename, Android-Auto-Label und Projektname auf Adolar Next setzen;
- eigene Versionslinie beginnen;
- bestehendes Server-Produkt-Headerfeld vorerst als `android` belassen, da der
  aktuelle Server andere Werte ablehnt;
- vor dem ersten Release ein optisch unterscheidbares Next-Launcher-Icon
  bereitstellen;
- Debug- und Release-Signing prüfen. Ein gemeinsamer Signaturschlüssel ist bei
  unterschiedlichen Application IDs zulässig, getrennte Schlüssel ebenfalls.

**Abnahme:** Beide Paketnamen sind gleichzeitig mit `adb shell pm list packages`
sichtbar, beide Launcher starten die jeweils richtige App und das Installieren
einer neuen Next-APK verändert weder App-Daten noch Version von Adolar Radio.

### Phase 1 – Architekturgrundlage und Testgerüst

**Ergebnis:** Die bisher große Activity/Service-Struktur kann erweitert werden,
ohne UI, Datenbank, Scanner und Netzwerk eng zu koppeln.

- Packages beziehungsweise Module für `data/local`, `data/remote`, `sync`,
  `scanner`, `playback` und `ui` anlegen;
- Repository-Schicht als einzige Schnittstelle der UI definieren;
- Room, WorkManager, Lifecycle/ViewModel und AndroidX-Testabhängigkeiten
  ergänzen;
- Executor-Regeln festlegen: keine Room-, Scanner- oder Netzwerkoperation auf
  dem Main Thread;
- zentralen `TrackRef` mit Quelle `LOCAL` oder `REMOTE` einführen;
- gemeinsame Konstantanten für 50-%-Scrobble- und 90-%-Playcount-Schwelle;
- vorhandene Source-Tests für den Media-Service weiterlaufen lassen.

**Tests:** Repository-Unit-Tests, Room-In-Memory-Test, Start der alten
Radiooberfläche als Smoke-Test.

### Phase 2 – Lokale Bibliothek als erster vollständiger Durchstich

**Ergebnis:** Ordner auswählen → scannen → Titel sehen → lokalen Titel
abspielen, vollständig im Flugmodus.

- Room-Schema v1 implementieren: `library_roots`, `local_tracks`,
  `track_state` und Scanstatus;
- `ACTION_OPEN_DOCUMENT_TREE` mit persistierter Leseberechtigung einbauen;
- rekursiven SAF-Scanner für MP3, FLAC, M4A, OGG, Opus, AAC und WAV umsetzen;
- Adolar-kompatible Metadaten, Änderungszeit, Größe und Dokument-ID speichern;
- inkrementellen Rescan und Behandlung entzogener/ungültiger URIs umsetzen;
- eingebettete Cover verkleinert in einem begrenzten App-Cache ablegen;
- einfachen Titelscreen und lokalen Media3-Start über `content://` liefern;
- Scan-Fortschritt, Fehlerzahl und Abbruch in der UI anzeigen.

**Tests:** kleine und große Testordner, fehlende Tags, doppelte Dateien,
SD-Kartenentnahme, entzogenes Ordnerrecht, Prozessabbruch während Scan sowie
Wiedergabe bei gesperrtem Bildschirm.

### Phase 3 – Adolar-Next-Navigation nach den Skizzen

**Ergebnis:** Die vollständige lokale Bibliothek ist über die Rakete erreichbar
und besitzt den vorgesehenen PlayerPro-inspirierten Aufbau im Adolar-Design.

- Raketen-Button und seitlichen Drawer implementieren;
- Schnellzugriffe, Suche, Alben, Interpreten, Genres, Playlists, Ordner, Titel,
  Radios, Sync und Einstellungen einbauen;
- gemeinsame Toolbar und typisierte Drei-Punkte-Menüs erstellen;
- Raster für Alben/Interpreten/Genres, Listen für Titel/Ordner/Playlists;
- permanenten Mini-Player mit Tap zum großen Player integrieren;
- Adolar-Violett, eigene/Material-Vektoricons, Kontrast und mindestens 48-dp-
  Touchflächen sicherstellen;
- leere, ladende, offline und fehlerhafte Zustände gestalten;
- `Radios` nur mit verbundenem Adolar befüllen; offline darf eine gecachte
  Liste sichtbar, aber nicht startbar sein.

**Tests:** Navigation und Zurück-Verhalten, Rotation/Prozessneustart,
TalkBack-Beschriftungen, große Schrift, kleine Displays und lange Metadaten.

### Phase 4 – Lokale Filter, Smart-Regeln und Playlists

**Ergebnis:** Web-ähnliche Bibliotheksarbeit funktioniert vollständig offline.

- Facettensuche und Sortierungen als indizierte Room-Queries umsetzen;
- versionierten `all`-/`any`-Filterbaum mit Web-Feldern und Operatoren
  implementieren;
- konventionellen Filtereditor erstellen;
- deterministischen deutschen Smart-Rule-Parser nach Java portieren;
- Golden-Testfälle zwischen Python- und Java-Parser teilen;
- `playlists` und `playlist_tracks` mit expliziter Reihenfolge ergänzen;
- Standard- und intelligente Playlist über den Plus-Dialog erstellen;
- Systemlisten für neu, häufig, kürzlich, selten und nie gespielt liefern;
- Queue-Aktionen und typisierte Kontextmenüs implementieren.

**Nicht in dieser Phase:** Synchronisation lokaler Playlists zu Adolar Web.
Dafür fehlen dem Server Revisionen, Tombstones und Konfliktregeln.

**Tests:** identische Filterresultate für gemeinsame Fixtures, verschachtelte
Regeln, Bibliotheksänderung bei offener Smart-Playlist, Reihenfolge statischer
Playlist und Schutz der Systemlisten.

### Phase 5 – Hybrid-Player

**Ergebnis:** Lokale Musik und bestehende Adolar-Radios benutzen eine robuste
MediaSession und dieselbe Bedienoberfläche auf Handy, Sperrbildschirm,
Bluetooth und Android Auto.

- Queue-Abstraktion auf `LOCAL` und `REMOTE` erweitern;
- lokalen Content-DataSource-Pfad vom HTTP-Cache trennen;
- Queue, Quelle, Track und Position wiederherstellbar persistieren;
- großen Player an Quelle, Playlist-/Radioname und lokale Metadaten anbinden;
- Rakete auch im großen Player als Drawer-Button verwenden;
- bisher getrennte Favorit-/Love-Aktionen in `Lieben` zusammenführen;
- Android-Auto-Browser um lokale Musik und lokale Playlists erweitern;
- Shuffle-Zustand und gemischte lokale Queue über MediaSession, Prozessneustart
  und Android Auto konsistent halten;
- **TODO Crossfade:** lokale Folgetitel sicher vorladen und ein konfigurierbares
  Crossfade ohne doppelten Audiofokus, ausgelassene Playcounts oder hörbare
  Pegelsprünge ergänzen. Das bestehende Crossfade der Adolar-Radios bleibt
  davon unberührt.

**Tests:** Wechsel Local ↔ Adolar-Radio, Next/Previous, Queue-Ende, Audiofokus,
Bluetooth, Notification, Sperrbildschirm, Android Auto und Prozessneustart.

**Android-Auto-Abnahme:** Ohne Serververbindung lassen sich lokale Musik und
Playlists durchsuchen, starten, pausieren, vor-/zurückschalten und mischen. Mit
Verbindung erscheinen zusätzlich die Adolar-Radios. Alle Aktionen arbeiten auf
derselben Queue und demselben Wiedergabestatus wie die Handy-App.

### Phase 6 – Offline-Playcount und Sync-Outbox

**Ergebnis:** Kein Play und keine Love-Aktion geht bei fehlendem Netz oder
App-Abbruch verloren.

Für Hörereignisse umgesetzt (Love-Aktionen folgen mit Phase 8):

- ✅ Room-Tabellen `sync_outbox` und `sync_receipts` ergänzt;
- ✅ UUID pro unveränderlichem Client-Ereignis erzeugt;
- ✅ lokale Zustandsänderung und Outbox-Insert in einer Transaktion;
- ✅ bei 50 % plus 30 Sekunden Last.fm-Fähigkeit vormerkt;
- ✅ bei 90 % lokalen Adolar-Playcount genau einmal erhöht;
- ✅ `started`, `skipped` und `completed` samt Startzeit/Position erfasst;
- ✅ WorkManager-Batchsync mit Netzwerkbedingung und exponentiellem Backoff
  (gegen einen austauschbaren `SyncBatchSender`; die konkrete
  401/429/5xx-Behandlung folgt mit dem echten Endpunkt in Phase 7);
- ⬜ Sync-Screen und kleine Zustandsanzeige im Drawer/Player umsetzen (noch
  offen, bewusst nach dem Outbox-Kern zurückgestellt).

**Tests:** Flugmodus vor/während/nach Wiedergabe, Timeout nach erfolgreicher
Serverannahme, mehrfacher Workerstart, Prozess-Kill, Reboot und Loginablauf.

### Phase 7 – Adolar-Mobile-Backend

**Ergebnis:** Adolar nimmt Android-Ereignisse genau einmal an und ordnet lokale
Titel sicher seiner Bibliothek zu.

- widerrufbares, gehasht gespeichertes Mobile-Gerätetoken einführen;
- `POST /api/android/v1/tracks/match` als Batch implementieren;
- Matchfolge: gespeicherter Link, MusicBrainz-ID, normalisierte Metadaten plus
  Album/Dauertoleranz;
- mehrdeutige Treffer niemals automatisch anwenden;
- `POST /api/android/v1/events/batch` implementieren;
- Eindeutigkeit `(user_id, device_id, event_id)` in der Datenbank erzwingen;
- Playcount und Archivbeitrag transaktional genau einmal aktualisieren;
- Adolar4U-Quelle `android_local` ergänzen und Events bei aktivierter Sammlung
  einfügen;
- nicht gematchte Events behalten und nach Server-Bibliotheksscans erneut
  zuordnen;
- serverseitige Integrations-Outbox für Last.fm anlegen.

**Tests:** pytest-Vertragstests, doppelte Batches, parallele Requests, falscher
Benutzer/Track, mehrdeutiges Matching, spätes Matching und deaktiviertes
Adolar4U.

### Phase 8 – „Lieben“ und Last.fm

**Ergebnis:** Die eine Android-Aktion verhält sich in jedem Verbindungszustand
vorhersagbar.

- lokal immer sofort Favorit setzen und `love_set` vormerken;
- mit Adolar-Match: persönliche Adolar-Favoritenplaylist aktualisieren;
- mit Last.fm am Adolar-Konto: Love/Unlove über serverseitige Outbox ausführen;
- ohne Match Last.fm anhand Künstler/Titel bedienen, Adolar-Favorit parken;
- Teilfehler getrennt zurückmelden, ohne lokalen Zustand zurückzurollen;
- ursprünglichen UTC-Startzeitpunkt an Last.fm-Scrobbles übergeben;
- serverseitige Last.fm-Jobs durch Event-ID deduplizieren.

Ein direkter Standalone-Last.fm-Modus folgt erst danach als eigene Scheibe. Er
benötigt API-Key, Shared Secret und Session Key; ein in der APK eingebettetes
Secret ist extrahierbar. Bevorzugt wird deshalb die Last.fm-Verbindung des
angemeldeten Adolar-Benutzers.

### Phase 9 – Härtung und Next-Beta

**Ergebnis:** Eine installierbare Beta kann parallel zur alten App im Alltag
verwendet werden.

- Room-Migrationstests für jede veröffentlichte Schema-Version;
- Performanceprofil mit 1.000, 10.000 und 50.000 Titeln;
- Akku-/Worker-/Scanner-Verhalten prüfen;
- Datenschutzansicht für lokal gespeicherte Metadaten und Sync-Historie;
- App-Datenexport/-reset und Ordnerentfernung mit klarer Wirkung;
- eigenes Next-Icon, Screenshots, README und Hilfeseite;
- Debug- und signierte Release-APK bauen;
- Koexistenz- und Update-Matrix auf mindestens API 23, 28, 30, 33 und 35;
- kontrollierte Beta, während Adolar Radio als Rückfalloption installiert
  bleibt.

## Abhängigkeiten und kritischer Pfad

```text
App-Identität
  -> Room + Scanner
  -> lokale Titelwiedergabe
  -> Navigation/Bibliothek
  -> Filter + Playlists
  -> Hybrid-Player
  -> lokale Outbox
  -> Backend-Matching + idempotenter Batch
  -> Last.fm/Lieben
  -> Beta-Härtung
```

Backend und Android können ab Phase 6 parallel entwickelt werden, sobald das
versionierte JSON-Vertragsfixture feststeht. Die App darf aber erst gegen eine
Produktivinstanz synchronisieren, wenn die serverseitige Idempotenz vollständig
getestet ist.

## Bewusst nicht Teil der ersten Next-Beta

- Herunterladen von Adolar-Servertracks als Offlinekopie;
- Google Cast;
- Schreiben oder Löschen von Audiodateien und Tags;
- Audio-Fingerprinting/Chromaprint;
- bidirektionale Playlist-Synchronisation mit Konfliktauflösung;
- Übernahme privater Daten aus der bisherigen App;
- direkt in der APK eingebettete Last.fm-Secrets.

Diese Grenzen verhindern, dass die erste Beta Dateiverwaltung, DRM-/Download-
Fragen oder unsichere Secrets mit dem Kernziel vermischt: lokale Dateien sicher
offline abspielen und Höraktionen später zuverlässig mit Adolar synchronisieren.
