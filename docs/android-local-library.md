# Adolar Android: lokale Bibliothek und Offline-Sync

Stand: 15. August 2026
Feature-Branch: `codex/android-local-library-sync`

## Zielbild

Adolar Android soll auch ohne konfigurierten oder erreichbaren Adolar-Server als
lokaler Musikplayer funktionieren. Nach der einmaligen Freigabe eines oder
mehrerer Musikordner müssen folgende Funktionen vollständig offline verfügbar
sein:

- inkrementelles Einlesen der freigegebenen Ordner und lokales Speichern der
  Titelmetadaten nach dem Adolar-Datenmodell;
- Bibliothekssuche, Facettenfilter, statische und smarte Playlists;
- lokale Wiedergabe einschließlich Hintergrundwiedergabe und Android Auto;
- lokaler Playcount und lokaler Favoritenstatus;
- dauerhafte Warteschlange für noch nicht übertragene Hör-, Favoriten- und
  Last.fm-Aktionen.

Sobald wieder Netzwerk verfügbar ist, synchronisiert die App ausstehende
Aktionen. Wiederholte Requests dürfen Playcounts oder Last.fm-Scrobbles nicht
verdoppeln.

## Befund im aktuellen Stand

### Android

Die Android-App ist aktuell ein kleiner Java-Client aus einer `MainActivity`
und einem `AdolarMediaService`:

- Media3/ExoPlayer spielt ausschließlich Adolar-Streams über
  `/api/stream/<track-id>`;
- die lokale 384-MB-Cache-Schicht ist ein Stream-Cache, keine offline
  durchsuchbare Musikbibliothek;
- es gibt weder Room/SQLite noch einen Dateiscanner, WorkManager oder eine
  dauerhafte Sync-Warteschlange;
- es gibt keine Ordnerfreigabe über das Storage Access Framework;
- Anmeldung erfolgt über ein Session-Cookie, das für einen langlebigen
  Hintergrund-Sync ungeeignet ist;
- Favorit und Last.fm-Love sind aktuell zwei getrennte Aktionen;
- der Service sendet für angemeldete Benutzer bereits `started`, `skipped` und
  `completed` an `/api/adolar4u/events/<track-id>`. Das funktioniert aber nur
  für bekannte Server-Track-IDs und erhöht keinen Adolar-Playcount;
- Android sendet derzeit weder `/api/track/<id>/played` noch
  `/api/lastfm/scrobble`.

### Adolar Web/Backend

Ein großer Teil der Fachlogik existiert bereits und sollte als Vertrag für die
Android-Implementierung dienen:

- Trackfelder: Titel, Künstler, Album, Album-Künstler, Genre, Jahr,
  Tracknummer, Dauer, Bitrate, Größe, Cover, BPM, Änderungs- und
  Hinzufügezeitpunkt;
- Facettenfilter und sortierte Suche;
- verschachtelte `all`-/`any`-Filterbäume, relative `added`-Regeln und der
  deterministische deutsche Smart-Rule-Parser;
- statische und smarte Playlists;
- persönliche Playcounts, persönliche Favoriten und Last.fm-Loved-Titel;
- idempotente Adolar4U-Events über `client_event_id`.

Die vorhandenen APIs reichen für lokale Handydateien trotzdem nicht aus:

- Playcount, Favorit und Adolar4U akzeptieren nur eine Adolar-Track-ID;
- `/api/track/<id>/played` ist nicht idempotent;
- `/api/lastfm/scrobble` ist nicht idempotent und übernimmt aktuell keinen vom
  Client gelieferten ursprünglichen Startzeitpunkt;
- der bestehende Favoriten-Endpunkt liebt nur bei aktivem
  `auto_love_favorites` und synchronisiert synchron;
- die Server-Tabelle `tracks` darf nicht für reine Handydateien verwendet
  werden: ihr `path` bezeichnet eine für Adolar Web erreichbare Serverdatei.

## Vorgeschlagene Android-Architektur

### 1. Ordnerzugriff und Scanner

Ordner werden über `ACTION_OPEN_DOCUMENT_TREE` ausgewählt. Die App übernimmt
die persistierbare Leseberechtigung und speichert die Tree-URI. Dadurch braucht
die ordnerbasierte Variante keine pauschale Speicherberechtigung. Der Scanner
läuft außerhalb des UI-Threads und besucht Unterordner rekursiv.

Android 11 und neuer lassen über den Systemdialog unter anderem weder den
Speicher-Root noch den Download-Root als Tree-Auswahl zu. Das muss die UI
erklären. Wenn eine Datei verschoben oder gelöscht wird, kann auch eine
persistierte URI ungültig werden; ein Rescan markiert den Datensatz dann als
fehlend, bevor er nach einer Schonfrist entfernt wird.

Unterstützte Formate sollen zunächst der Serverlogik entsprechen:

`mp3`, `flac`, `m4a`, `ogg`, `opus`, `aac`, `wav`.

Metadaten werden über `MediaMetadataRetriever` beziehungsweise einen kleinen
Tag-Reader aus dem `ParcelFileDescriptor` gelesen. Fehlende Titel fallen auf
den Dateinamen zurück. Cover werden verkleinert im App-Cache gespeichert, nicht
als große BLOBs in der Bibliotheksdatenbank. Der erste Scan zeigt Fortschritt;
weitere Scans vergleichen Dokument-ID, Änderungszeit und Größe und lesen nur
geänderte Dateien neu ein.

### 2. Lokale Datenbank

Room ist für die bestehende reine Java-App geeignet und bietet geprüfte Queries
und Migrationen. Mindestens folgende Tabellen werden benötigt:

| Tabelle | Zweck |
| --- | --- |
| `library_roots` | Tree-URI, Anzeigename, Berechtigungszustand, letzter Scan |
| `local_tracks` | Adolar-kompatible Metadaten, Content-URI, stabile lokale ID, Scanstatus |
| `playlists` | Name, `static`/`smart`, Filter-JSON, Sortierung |
| `playlist_tracks` | geordnete Zuordnung statischer Playlists |
| `track_state` | lokaler Playcount, letzter Playzeitpunkt, Favorit |
| `remote_track_links` | lokale ID zu Adolar-Track-ID, Matchart und Konfidenz |
| `sync_outbox` | unveränderliche Aktionen mit UUID, Versuchszahl und Retry-Zeit |
| `sync_receipts` | optionaler lokaler Nachweis bereits bestätigter Aktionen |

`local_tracks` sollte das Servermodell spiegeln und zusätzlich `document_uri`,
`document_id`, `mime_type`, `display_name`, `missing_since` und eine
`identity_key` besitzen. Eine Room-Migration ist für jede Schemaänderung zu
testen; `fallbackToDestructiveMigration` ist für Nutzerdaten ausgeschlossen.

### 3. Track-Identität

Eine lokale Content-URI ist nur auf einem Gerät stabil und darf nie als globale
Trackidentität dienen. Die Zuordnung zu Adolar erfolgt in dieser Reihenfolge:

1. bereits bestätigte Zuordnung aus `remote_track_links`;
2. MusicBrainz Recording ID, sobald Scanner und Servermodell dieses Tag lesen;
3. normalisierter Künstler + Titel, bewertet mit Album und Dauer (Toleranz
   maximal drei Sekunden);
4. bei mehreren gleich guten Kandidaten: `ambiguous`, keine automatische
   Playcount-/Favoritenänderung.

Audio-Fingerprinting wäre genauer, vergrößert Android- und Serverumfang aber
deutlich und ist kein Bestandteil der ersten Version. Reine Handydateien
werden nicht als Fake-Tracks in die Serverbibliothek eingetragen.

Ist ein Titel noch nicht auf dem Server vorhanden, bewahrt Adolar das Mobile-
Event als `unmatched` auf. Nach einem späteren Server-Scan wird erneut gematcht
und die Wirkung dann genau einmal nachgezogen. Solange kein Match existiert,
kann der Titel zu Last.fm gescrobbelt werden, aber keinen trackbezogenen
Adolar-Playcount und kein direktes Adolar4U-Tracksignal erzeugen.

### 4. Bibliothek, Filter und Playlists

Die lokale UI folgt den Entwürfen aus `I:\Downloads\adoloar android menüs` und
übernimmt deren an PlayerPro angelehntes Navigationsprinzip. Die bestehende
Activity sollte dabei in kleinere Screens plus Repository-Schicht zerlegt
werden; ein vollständiger Wechsel zu Compose ist dafür nicht nötig.

#### Verbindliche Navigation aus den Entwürfen

Die Rakete links oben ist auf allen Hauptscreens der Menüknopf. Sie ersetzt
bewusst ein generisches Hamburger-Symbol und öffnet einen seitlichen
Bibliotheks-Drawer. Das Logo ist damit gleichzeitig Marke und konsistenter
Startpunkt der Navigation. Der Android-Zurück-Button schließt zuerst Drawer,
Dialog oder Kontextmenü und navigiert erst danach im Screen-Verlauf zurück.

Der Drawer aus `adolar_track_menü.png` wird fachlich so übernommen:

- **Schnellzugriff:** Favoriten, kürzlich hinzugefügt, häufig gespielt,
  kürzlich gespielt, selten gespielt und nie gespielt;
- **Bibliothek:** Suche, Alben, Interpreten, Genres, Playlists, Ordner und Titel;
- **Online:** `Radios` zeigt ausschließlich die Radiostationen des verbundenen
  Adolar-Servers. Adolar4U erscheint dort als Adolar-Station beziehungsweise
  Stations-Engine, wenn es für den angemeldeten Benutzer verfügbar ist;
- **System:** Bibliothek/Ordner verwalten, Sync-Status, Konto und Einstellungen.

Die Zähler rechts werden aus Room gelesen und bleiben daher offline verfügbar.
Für `Radios` darf die zuletzt erfolgreich geladene Senderliste lokal gecacht
und offline angezeigt werden. Da die Audiodateien vom Adolar-Server gestreamt
werden, sind Start und Fortsetzung einer Radiowiedergabe ohne Serververbindung
deaktiviert und eindeutig mit `Adolar nicht erreichbar` gekennzeichnet. Nach
dem Verbinden wird die Liste entsprechend öffentlichem oder angemeldetem
Serverzugriff aktualisiert.

`Am besten bewertet` aus der PlayerPro-Vorlage wird nicht ungeprüft übernommen:
Adolar kennt derzeit Favorit/Lieben, aber keine Mehrstufenbewertung. Der Eintrag
wird entweder durch `Favoriten` ersetzt oder erfordert später ein eigenes
Rating-Feld.

#### Gemeinsames Screen-Gerüst

Die Screens `adolar_android_genre.png`, `interpreten_dialog.png`,
`adolar_playlist_titel.png` und `playlist_dialog2.png` definieren ein
gemeinsames Gerüst:

- Toolbar mit Rakete, kontextabhängigem Icon und Titel;
- rechts Suche und Überlaufmenü; Cast wird nur gezeigt, wenn eine tatsächliche
  Cast-Integration umgesetzt wird und ist kein Bestandteil der ersten lokalen
  Version;
- Raster für Alben, Interpreten und Genres, Liste für Titel, Ordner und
  Playlists;
- Drei-Punkte-Menü pro Element mit genau auf diesen Elementtyp zugeschnittenen
  Aktionen;
- dauerhaft sichtbarer Mini-Player am unteren Rand, der Cover, Titel,
  Interpret und Play/Pause zeigt und per Tap den großen Player öffnet;
- laufender Titel und aktive Quelle werden in Listen eindeutig hervorgehoben.

Leere Zustände dürfen nicht nur eine leere Liste zeigen. Sie bieten je nach
Ursache `Musikordner auswählen`, `Erneut scannen`, `Filter zurücksetzen` oder
`Mit Adolar verbinden` an. Während des ersten Scans bleiben Fortschritt,
gefundene Titel und übersprungene Dateien sichtbar.

Die Entwürfe sind Strukturreferenzen, keine Quelle für fremde Icons oder
Grafikassets. Die Umsetzung benutzt das Adolar-Farbsystem (Violett statt des
PlayerPro-Grüns), Material-/eigene Vektoricons und ausreichend große
Touchflächen. Graue Sekundärtexte müssen den Android-Kontrastanforderungen
entsprechen.

#### Raster und Kontextaktionen

Der Interpreten-Screen übernimmt das zweispaltige Bildraster aus
`interpreten_dialog.png`; der Genre-Screen das entsprechende Coverraster aus
`adolar_android_genre.png`. Fehlt ein Bild, erscheint ein typisierter
Adolar-Platzhalter statt einer leeren Fläche. Interpret-/Genre-Bilder werden
lokal gecacht, damit die Raster auch offline stabil bleiben.

Das Genre-Menü aus dem Entwurf wird auf folgende konsistente Aktionen
normalisiert:

- wiedergeben;
- an die aktuelle Queue anhängen;
- als Nächstes wiedergeben;
- zufällig wiedergeben;
- alle Titel anzeigen;
- zu einer vorhandenen Playlist hinzufügen;
- zu Favoriten hinzufügen beziehungsweise lieben;
- Genre-Information anzeigen;
- Genrebild verwalten.

Genre-Informationen von Last.fm werden nach dem ersten Abruf gecacht und zeigen
offline den letzten Stand. `Löschen` darf in diesem Menü niemals kommentarlos
die Audiodateien löschen. Für Version 1 wird die Aktion weggelassen; ein
späteres `Aus Bibliothek ausblenden` oder `Genre-Tag entfernen` braucht eine
explizite Benennung und Bestätigung.

Für Titel, Alben, Interpreten und Playlists wird derselbe Aktionswortlaut
verwendet. `Zu akt. Playlist hinzufügen` aus der Vorlage wird in der UI als
`Zur aktuellen Queue hinzufügen` bezeichnet, damit Wiedergabequeue und
gespeicherte Playlist nicht verwechselt werden.

#### Playlists

Der Plus-Button aus `playlist_dialog.png` öffnet die Auswahl:

- **Standard-Playlist:** explizit ausgewählte, lokal geordnete Titel;
- **Intelligente Playlist:** gespeicherter Adolar-Filterbaum, der bei jedem
  Öffnen gegen die aktuelle lokale Bibliothek neu ausgewertet wird.

Das Playlist-Menü aus `playlist_dialog2.png` enthält Wiedergabe, Queue-Aktionen,
Zufallswiedergabe, Lieben/Favorisieren aller enthaltenen Titel, Bearbeiten,
Umbenennen und Löschen. Systemplaylists wie `Kürzlich hinzugefügt`, `Häufig
gespielt`, `Selten gespielt` und `Nie gespielt` können weder umbenannt noch
gelöscht werden. Destruktive Aktionen benötigen Bestätigung; sie löschen nie
die zugrunde liegenden Musikdateien.

#### Großer Player

`adolar_play_screen.png` ergänzt den bestehenden Player um den Raketen-Menüknopf
und die Anzeige der aktiven Quelle beziehungsweise des Radio-/Playlistnamens.
Der Quellwähler unterscheidet mindestens lokale Queue, lokale Playlist und die
Radios des verbundenen Adolar-Servers. Adolar4U ist dabei eine Adolar-Radioquelle
und kein separater lokaler Radiotyp. Im Offlinezustand bleiben lokale Quellen
auswählbar; Adolar-Radios zeigen ihren Verbindungszustand, ohne die lokale
Bedienung zu blockieren.

Der Entwurf zeigt noch getrennte Buttons für `Favorit` und `Lieben`. Für die in
diesem Dokument festgelegte Produktsprache werden sie zu einer einzigen Aktion
`Lieben` zusammengeführt. Ihr lokaler Zustand ist sofort sichtbar; ein kleines
Sync-Symbol unterscheidet bei Bedarf `nur lokal`, `ausstehend`, `synchronisiert`
und `Fehler`, ohne einen zweiten Love-Knopf einzuführen.

#### Offline- und Sync-Rückmeldung

Offline ist ein normaler Betriebszustand und kein modaler Fehler. Ein kleines
Statussymbol in Toolbar beziehungsweise Drawer zeigt:

- offline, lokale Funktionen verfügbar;
- Anzahl ausstehender Sync-Aktionen;
- laufende Synchronisation;
- Anmeldung erforderlich;
- dauerhafter Konflikt oder nicht zuordenbarer Titel.

Der Sync-Screen listet ausstehende und fehlgeschlagene Aktionen verständlich,
bietet `Jetzt synchronisieren` und erlaubt bei Validierungsfehlern Verwerfen
oder erneutes Zuordnen. Normale Netzwerkfehler verlangen keine Interaktion.

Für Web-Parität wird das Filterformat versioniert gemeinsam verwendet:

- Gruppen: `mode = all|any`, maximal vier Ebenen;
- Text: Titel, Künstler, Album und Genre;
- Zahlen: Jahr, Jahrzehnt, Dauer, Bitrate und BPM;
- Zeitpunkt: vor beziehungsweise innerhalb der letzten Tage/Wochen/Monate;
- Operatoren wie im Backend (`contains`, `equals`, `gt`, `lt` usw.);
- Sortierungen nach Künstler, Titel, Album, Jahr, Dauer und Playcount.

Der konventionelle Filtereditor und die Auswertung laufen vollständig lokal.
Der vorhandene Smart-Rule-Parser ist deterministisch; seine Grammatik kann nach
Java portiert und mit denselben Testfällen wie `adolar/smart_rules.py` geprüft
werden. So bleibt auch die natürlichsprachliche Smart-Filter-Eingabe offline
nutzbar. Gespeichert wird immer der interpretierte Filterbaum, nicht nur der
deutsche Eingabetext.

Playlists sind in der ersten Ausbaustufe lokal und offline vollständig nutzbar.
Eine spätere Playlist-Synchronisation mit Adolar Web braucht zusätzlich
Revisionen, `updated_at`, Tombstones und eine Konfliktoberfläche; die heutigen
Playlist-Endpunkte besitzen diese Grundlagen noch nicht. Playcount-, Hör- und
Favoritensync sind davon unabhängig.

### 5. Wiedergabe

Der Media-Service erhält eine gemeinsame Queue-Abstraktion mit zwei Quellen:

- `REMOTE`: heutige Adolar-Track-ID und Stream-URL;
- `LOCAL`: lokale Track-ID und `content://`-URI.

ExoPlayer kann die lokale Content-URI direkt als MediaItem abspielen. Der
HTTP-Cache wird nur für `REMOTE` benutzt. Queue, aktuelle Position und Quelle
werden gespeichert, damit ein Prozessneustart die Sitzung sinnvoll
wiederherstellen kann. Der MediaBrowser-Root bietet für Android Auto getrennte
Knoten für lokale Musik/Playlists und Adolar Radio an.

Beim Abspielen wird lokal sofort gezählt beziehungsweise vorgemerkt:

- Last.fm-Scrobble-fähig: mindestens 30 Sekunden und mindestens 50 Prozent;
- Adolar-Playcount: wie Adolar Web bei mindestens 90 Prozent;
- Adolar4U: `started` sowie `completed`/`skipped` mit tatsächlicher Position.

Die Schwellenwerte müssen als gemeinsame Konstanten dokumentiert und in
Android-/Backend-Vertragstests geprüft werden.

## Offline-Outbox

Jede relevante Änderung wird zuerst zusammen mit der lokalen Zustandsänderung
in einer Room-Transaktion geschrieben. Ein Outbox-Eintrag enthält mindestens:

- zufällige, dauerhaft stabile `event_id` (UUID);
- Gerät-ID und lokaler Trackschlüssel;
- Aktion und versionierte JSON-Nutzlast;
- Erstellzeitpunkt und bei Plays den tatsächlichen UTC-Startzeitpunkt;
- Zustand `pending`, `sending`, `confirmed` oder `permanent_error`;
- Versuchszahl, letzte Fehlermeldung und nächsten Retry-Zeitpunkt.

Ein WorkManager-Job mit Netzwerkbedingung überträgt Batches. Zusätzlich wird
bei App-Start, Login und Netzwiederkehr angestoßen. Timeouts, 5xx, 429 und
Verbindungsfehler bleiben mit exponentiellem Backoff in der Queue. 401 pausiert
bis zur erneuten Anmeldung. Validierungsfehler werden sichtbar als dauerhaft
fehlgeschlagen markiert. Bestätigte Einträge können nach einer Aufbewahrungszeit
kompaktiert werden.

Die App darf einen Eintrag nach unklarer Antwort erneut senden. Deshalb ist die
serverseitige Eindeutigkeit von `(user_id, device_id, event_id)` zwingend; nur
ein clientseitiges `sent`-Flag reicht nicht.

## Benötigte Backend-Erweiterung

### Authentifizierung

Beim Android-Login wird ein widerrufbares, langlebiges und auf Mobile-Sync
beschränktes Gerätetoken ausgegeben. Es wird serverseitig nur gehasht und auf
Android Keystore-gestützt verschlüsselt gespeichert. Session-Cookies bleiben
für interaktive Screens möglich, sind aber nicht die Identität des
Hintergrund-Syncs.

### Track-Matching

`POST /api/android/v1/tracks/match` nimmt bis zu etwa 200 lokale Identitäten pro
Batch entgegen. Die Antwort liefert pro lokaler ID `matched`, `ambiguous` oder
`unmatched`, eine Adolar-Track-ID und Matchart/-konfidenz. Ein explizit bereits
gematchter Server-Track wird weiterhin gegen den angemeldeten Benutzer und die
aktive Bibliothek validiert.

### Idempotenter Event-Batch

`POST /api/android/v1/events/batch` nimmt Hör- und Favoritenereignisse entgegen.
Beispiel eines Hörereignisses:

```json
{
  "event_id": "81681736-438d-41a7-bf87-7d9aa471d379",
  "kind": "playback",
  "local_track_id": "phone-track-42",
  "remote_track_id": 123,
  "identity": {
    "artist": "Artist",
    "title": "Title",
    "album": "Album",
    "duration_seconds": 241
  },
  "started_at": 1786812412,
  "position_seconds": 233,
  "duration_seconds": 241,
  "event_type": "completed",
  "source": "android_local"
}
```

Die Servertransaktion:

1. legt zuerst den eindeutigen Mobile-Receipt an;
2. löst oder validiert den Track;
3. erhöht bei mindestens 90 Prozent `user_play_counts` genau einmal und
   berücksichtigt die bestehende `contributes_playcount`-Berechtigung;
4. schreibt bei aktivierter Datensammlung ein Adolar4U-Ereignis mit Quelle
   `android_local` und derselben Client-ID;
5. legt bei vorhandenem Last.fm-Konto einen idempotenten Last.fm-Job mit dem
   ursprünglichen `started_at` an;
6. liefert je Event `applied`, `duplicate`, `unmatched`, `ambiguous` oder einen
   dauerhaften Validierungsfehler zurück.

Für unverknüpfte Titel wird das Receipt samt Metadaten behalten. Ein
Reconciliation-Job versucht die Zuordnung nach Bibliotheksscans erneut.

Vorgeschlagene neue Tabellen im inhaltsbezogenen Adolar-DB-Kontext:

- `android_devices` beziehungsweise gerätebezogene Token-Metadaten in der
  Control-DB;
- `android_track_links` mit optionaler `track_id`;
- `android_event_receipts` mit eindeutiger Event-ID, Nutzlast und
  Verarbeitungsmarkern;
- `lastfm_outbox` oder eine allgemeinere serverseitige Integrations-Outbox.

## Semantik der einzigen Aktion „Lieben“

Die Android-Oberfläche ersetzt die getrennten Knöpfe `Favorit` und `Love` für
lokale Titel durch eine einzige optimistische Aktion. Sie ändert immer zuerst
den lokalen Favoritenstatus und erzeugt ein `love_set`-Outbox-Event.

Priorität bei der Synchronisation:

1. **Mit angemeldetem Adolar und Track-Match:** Favorit in der persönlichen
   Adolar-Favoritenplaylist setzen; wenn für diesen Adolar-Benutzer Last.fm
   verbunden ist, zusätzlich dort lieben. Der Mobile-Endpunkt führt beides aus
   und meldet Teilfehler separat zurück.
2. **Ohne Adolar-Anmeldung, aber mit direkter Last.fm-Konfiguration:** nur
   Last.fm lieben; lokaler Favorit bleibt gesetzt.
3. **Ohne beide Verbindungen:** ausschließlich lokaler Favorit.
4. **Adolar verbunden, aber Track nicht gematcht:** lokaler Favorit bleibt;
   Last.fm kann anhand Künstler/Titel bedient werden, Adolar-Favorit wartet auf
   eine spätere Zuordnung.

`unlove` wird symmetrisch behandelt. Das unterscheidet sich bewusst vom
heutigen einseitigen `auto_love_favorites` und braucht einen eigenen
Mobile-Endpunkt statt einer stillen Wiederverwendung von `/api/favorites`.

## Last.fm-Authentifizierung

Ein Last.fm-Benutzername oder kurzlebiger Auth-Token allein reicht nicht. Für
signierte Schreibzugriffe werden API-Key, Shared Secret und ein nach der
Browserfreigabe erhaltener Session Key benötigt. Der Session Key ist langlebig,
kann aber durch den Benutzer widerrufen werden.

Empfehlung:

- primär Last.fm über das angemeldete Adolar-Konto bedienen; API-Secret und
  Retry-Queue bleiben dann auf dem Server;
- optional einen echten Standalone-Modus anbieten. Dafür benötigt Adolar
  Android eine eigene Last.fm-App-Registrierung oder vom Benutzer eingetragene
  API-Zugangsdaten. Ein in der APK eingebettetes Shared Secret ist extrahierbar
  und darf nicht als wirklich geheim betrachtet werden;
- Session Key auf dem Gerät Keystore-gestützt speichern, Last.fm-Aktionen
  ebenfalls offline in der Outbox parken und mit ihrem ursprünglichen
  Hörzeitpunkt übertragen.

## Umsetzung in sinnvollen Scheiben

1. **Vertrag und Testdaten:** gemeinsames Track-/Filter-/Eventformat,
   Schwellenwerte, Matchregeln und Golden Tests festlegen.
2. **Offline-Fundament:** Room-Schema, Ordnerauswahl, persistierte URI-Rechte,
   inkrementeller Scanner und lokale Covers.
3. **Lokale Bibliothek:** Suche, Filter, statische/smarte Playlists und lokaler
   Favorit; vollständig im Flugmodus testen.
4. **Hybrid-Player:** lokale MediaItems, Queue-Wiederherstellung, MediaSession,
   Notification und Android Auto; Server-Radio unverändert erhalten.
5. **Outbox:** lokale Play-/Love-Ereignisse, WorkManager, Backoff,
   Prozess-/Reboot-Sicherheit und Sync-Statusanzeige.
6. **Backend:** Gerätetoken, Match- und Batch-API, Receipt-Tabellen,
   Reconciliation und Integration in Playcount/Adolar4U.
7. **Last.fm und Lieben:** einheitliche Aktion, serververmittelter Last.fm-Sync,
   danach optionaler Standalone-Last.fm-Modus.
8. **Härtung:** Room-Migrationstests, große Bibliotheken, entzogenes
   Ordnerrecht, SD-Kartenentnahme, Konflikte, Rate Limits und Dubletten.

## Abnahmekriterien

- Die App startet ohne Server-URL und zeigt nach Ordnerfreigabe die lokale
  Bibliothek.
- Nach einem erfolgreichen Scan funktionieren Neustart, Suche, Filter,
  Smart-Playlist, Favorit und Wiedergabe im Flugmodus.
- Ein Rescan liest unveränderte Dateien nicht erneut ein und behandelt gelöschte
  oder verschobene Dateien nachvollziehbar.
- Lokale Wiedergabe läuft bei gesperrtem Bildschirm und über Android Auto
  weiter.
- Nach 90 Prozent wird lokal genau ein Play gezählt. Nach Netzrückkehr kommt
  derselbe Play beim Adolar-Benutzer genau einmal an, auch nach Timeout,
  Prozessabbruch oder Geräte-Neustart.
- Ein angenommener Play liefert bei aktivem Adolar4U ein verwertbares
  `android_local`-Ereignis.
- Last.fm erhält den ursprünglichen Hörzeitpunkt und keinen doppelten Scrobble.
- „Lieben“ folgt in allen vier Verbindungszuständen der oben definierten
  Priorität und bleibt bei Offline-Nutzung sichtbar ausstehend.
- Unbekannte oder mehrdeutige Titel verändern keine falschen Adolar-Tracks und
  können nach einem späteren Server-Scan nachträglich zugeordnet werden.

## Relevante Primärquellen

- Android Storage Access Framework und persistierbare URI-Rechte:
  <https://developer.android.com/training/data-storage/shared/documents-files>
- Room für lokale strukturierte Offline-Daten:
  <https://developer.android.com/training/data-storage/room/>
- Media3 MediaItems:
  <https://developer.android.com/media/media3/exoplayer/media-items>
- Last.fm Desktop-Authentifizierung:
  <https://www.last.fm/api/desktopauth>
- Last.fm `track.scrobble` einschließlich UTC-Zeitstempel:
  <https://www.last.fm/api/show/track.scrobble>
