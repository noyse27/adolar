# Playback-Refactoring: Trackwechsel, Preloading, Cache und Crossfade

Stand: 8. August 2026

## Ziel dieses Dokuments

Dieses Dokument ist ein technisches Handoff für die weitere Arbeit am Adolar-
Playback. Es beschreibt den aktuell untersuchten Aufbau, die wahrscheinlichsten
Ursachen der hörbaren Ladepausen und ausbleibenden Crossfades sowie mehrere
abgestufte Lösungsstrategien.

Der wichtigste Befund lautet: Die größten Browserprobleme entstehen nicht nur
durch zu wenig Cache. Der Hauptplayer verwirft beim Crossfade den bereits
laufenden, vorgepufferten Folgetrack und öffnet ihn anschließend erneut. Im
Radio-Modus kommt zusätzlich ein synchroner Queue-Refill während des
Trackwechsels hinzu. Beide Probleme sollten vor einer größeren Cache- oder
Streaming-Umstellung behoben werden.

Bis zur Erstellung dieses Dokuments wurden keine Playback-Änderungen
implementiert.

## Betroffene Komponenten

- Haupt-Webplayer: `static/js/app.js`
- Eigenständige Radio-Webseite: `templates/radio.html`
- Audio-Streaming-Endpunkt: `app.py`, Route `/api/stream/<track_id>`
- Deployment: `Dockerfile` und `docker-compose.yml`
- Native Android-Wiedergabe:
  `adolar-android/app/src/main/java/net/polze/adolarradio/AdolarMediaService.java`
- Android-Abhängigkeiten: `adolar-android/app/build.gradle`

## Aktueller Aufbau

### Haupt-Webplayer

Der Hauptplayer besitzt zwei feste HTML-Audioelemente:

- `audio` ist das primäre Element.
- `audioB` ist das Preload- und Crossfade-Element.

Die Crossfade-Konfiguration liegt derzeit bei:

- Preload-Beginn: 25 Sekunden vor Trackende (`CF_PRELOAD`)
- Fade-out: 12 Sekunden (`CF_OUT`)
- Fade-in: 8 Sekunden (`CF_IN`)

Der Folgetrack wird mit `preloadNext()` in `audioB` geladen. Der Fade startet,
sobald `audioB.readyState >= 3` meldet. Die Lautstärken werden alle 50 ms per
JavaScript-Timer verändert.

### Eigenständige Radio-Webseite

`templates/radio.html` besitzt ebenfalls zwei Audioelemente, behandelt sie aber
anders. Dort ist `audio` eine veränderliche Referenz auf das aktive Element.
Nach dem Crossfade wird das vorgeladene Element zum aktiven Element erklärt,
ohne seinen Stream neu zu öffnen. Das alte Element wird anschließend geleert
und als zukünftiger Preload-Slot wiederverwendet.

Dieser Ansatz ist die richtige Ausgangsbasis für den Haupt-Webplayer.

### Android

Die native Android-App verwendet einen einzelnen Media3-ExoPlayer. Der aktuelle
Track ist der erste `MediaSource`; genau ein weiterer Track wird frühzeitig per
`player.addMediaSource()` an die Playlist angehängt.

Das liefert im Erfolgsfall eine gapless Playlist-Transition. Es ist jedoch kein
echter Crossfade, weil nie zwei Tracks gleichzeitig decodiert und abgespielt
werden. Außerdem werden derzeit weder ein persistenter Media3-Cache noch ein
dedizierter PreloadManager oder ein angepasstes LoadControl verwendet.

Die App verwendet Media3 1.4.1.

### Streaming-Backend

`/api/stream/<track_id>` löst bei jeder Anfrage zuerst die Track-ID über SQLite
zum Dateipfad auf. Range-Anfragen werden mit einem eigenen Python-Generator in
64-KB-Blöcken ausgeliefert. Die manuell erzeugten `206`-Antworten besitzen zwar
`Content-Range`, `Accept-Ranges`, `Content-Length` und `Content-Type`, aber keine
expliziten Cache-, ETag- oder Last-Modified-Header.

Gunicorn läuft im Docker-Setup mit zwei Workern und vier Threads pro Worker.
Ein Crossfade kann pro Client zwei parallele Audiostreams belegen. Lang laufende
Streams können daher mit Queue-, Telemetrie- oder UI-Anfragen um die verfügbaren
Threads konkurrieren.

## Konkrete Fehlerursachen

### 1. Der Browser verwirft den funktionierenden Preload

In `startNormalCrossfade()` geschieht am Ende des Fades Folgendes:

1. Quelle und Position von `audioB` werden gelesen.
2. `audioB` wird pausiert.
3. Das `src` von `audioB` wird entfernt und `load()` aufgerufen.
4. Dieselbe URL wird `audio.src` zugewiesen.
5. `audio.currentTime` wird auf die bisherige Position gesetzt.
6. `audio.play()` wird erneut aufgerufen.

Der Radio-Crossfade des Hauptplayers verwendet dasselbe Muster.

Damit gehen der bereits aufgebaute Netzwerkpuffer, der Decoderzustand und die
laufende Wiedergabe verloren. Der Browser muss den Stream erneut öffnen,
Metadaten einlesen und zur bisherigen Position springen. Je nach Codec,
Dateigröße, NAS-Latenz und Browser können dadurch hörbare Pausen oder ein
fehlgeschlagener Handoff entstehen.

Relevante Stellen:

- `static/js/app.js`, Funktion `startNormalCrossfade()`, ungefähr Zeile 2140
- `static/js/app.js`, Funktion `startCrossfade()`, ungefähr Zeile 2196
- funktionierendes Vergleichsmuster in `templates/radio.html`, Funktionen
  `getInactive()` und `startCrossfade()`, ungefähr Zeilen 727 bis 817

### 2. Synchroner Queue-Refill blockiert den Web-Radiowechsel

`radioNext()` entfernt zuerst den gespielten Track. Wenn die Queue danach fünf
oder weniger Einträge enthält, wird `loadRadioQueue()` mit `await` aufgerufen.
Erst nach dieser Serverantwort wird der neue aktuelle Track vollständig
übernommen.

Beim Crossfade wurde das bereits spielende `audioB` zu diesem Zeitpunkt jedoch
schon pausiert und geleert. Die Wartezeit der Empfehlungs- oder Radio-API wird
dadurch direkt zur hörbaren Pause.

Da Queue und Refill jeweils in Fünferblöcken arbeiten, tritt dieser Pfad ungefähr
alle fünf Titel auf. Wenn der anfängliche Hintergrund-Refill nicht rechtzeitig
fertig ist, kann er bereits beim ersten Wechsel auftreten.

Relevante Stelle:

- `static/js/app.js`, Funktion `radioNext()`, ungefähr Zeilen 2013 bis 2076

Die eigenständige Radio-Seite startet den Refill dagegen im Normalfall
asynchron und blockiert den Trackwechsel nicht.

### 3. `readyState >= 3` ist kein ausreichender Crossfade-Nachweis

Der Hauptplayer prüft nur, ob das inaktive Audioelement grundsätzlich zukünftige
Daten besitzt. Er prüft nicht, wie viele Sekunden tatsächlich in
`audio.buffered` verfügbar sind.

Ein Track kann daher `canplay` melden, obwohl nicht genug Material für den
achtsekündigen Fade-in plus einen Sicherheitspuffer geladen wurde. Bei einem
langsamen Stream kann der Folgetrack mitten im Fade erneut in `waiting` oder
`stalled` wechseln.

### 4. Preloading beginnt unnötig spät

Der nächste Track steht bei Radio, Shuffle und Playlists normalerweise schon
lange vor den letzten 25 Sekunden fest. Trotzdem beginnt der Audio-Preload erst
kurz vor Trackende. Auf mobilen Browsern oder bei Hintergrund-Tabs ist
`preload="auto"` außerdem nur eine Empfehlung und kann vom Browser gedrosselt
werden.

### 5. Android implementiert keinen echten Crossfade

`AdolarMediaService` verwendet nur einen ExoPlayer. Das Anhängen einer weiteren
MediaSource ermöglicht eine Playlist-Transition, aber keine zeitliche
Überlappung. Die Aussage, ein Android-Crossfade werde manchmal nicht ausgeführt,
ist daher technisch erwartbar: Im nativen Service existiert zurzeit keine
Crossfade-Implementierung.

### 6. Android puffert nur indirekt über die Standard-Playlist

`queueNextTrack()` lädt frühzeitig die Metadaten für genau einen weiteren Track
und hängt dessen MediaSource an. Wann und wie viel Audio ExoPlayer tatsächlich
lädt, bleibt dem Standard-LoadControl überlassen. Ein Disk-Cache oder ein
explizites Vorladen einer Mindestdauer existiert nicht.

Wenn die MediaSource am Trackende noch nicht vorbereitet ist, fällt der Service
in `STATE_ENDED` zurück und ruft erst dann `loadNextTrack()` auf. Dieser
Fallback enthält eine weitere API-Anfrage und einen vollständigen
`prepare()`-Zyklus.

### 7. Streaming-Antworten sind nicht auf Wiederverwendung optimiert

Die Stream-URL enthält nur die Track-ID. Es gibt keine Inhaltsversion in der URL.
Deshalb kann das Backend nicht ohne Weiteres lange `immutable`-Cachezeiten
setzen, da sich eine Datei theoretisch unter derselben Track-ID ändern könnte.

Range-Antworten werden manuell aus Python gestreamt. Das ist funktional, aber
für mehrere parallele Audiostreams weniger effizient als eine Auslieferung durch
einen dafür optimierten Reverse Proxy oder Webserver.

## Strategie A: Handoff und Queue reparieren

Diese Strategie sollte zuerst umgesetzt werden. Sie behebt die beiden
deterministischen Hauptfehler ohne eine neue Infrastruktur.

### Zielarchitektur im Browser

- Beide Audioelemente sind gleichwertige Player-Slots.
- Eine veränderliche Referenz zeigt auf den aktiven Slot.
- `getInactiveAudio()` liefert jeweils den anderen Slot.
- Der Folgetrack bleibt beim Handoff in seinem ursprünglichen Element.
- Nach dem Fade wird nur die aktive Referenz ausgetauscht.
- Der alte Slot wird erst nach dem Tausch pausiert und geleert.
- Alle Audio-Events werden an beide Elemente gebunden und prüfen, ob ihr Ziel
  aktuell aktiv ist.

Pseudocode:

```javascript
const audioA = $("audio");
const audioB = $("audio-b");
let activeAudio = audioA;

function inactiveAudio() {
  return activeAudio === audioA ? audioB : audioA;
}

function finishCrossfade(incoming) {
  const outgoing = activeAudio;
  activeAudio = incoming;
  activeAudio.volume = targetVolume();

  outgoing.pause();
  outgoing.removeAttribute("src");
  outgoing.load();
}
```

Es darf beim erfolgreichen Handoff keine erneute Zuweisung derselben Stream-URL
und keinen `currentTime`-Transfer geben.

### Queue-Refill entkoppeln

- Der neue aktuelle Track wird sofort aus der vorhandenen Queue übernommen.
- Metadaten und UI werden sofort aktualisiert.
- Ein Refill wird bei Unterschreiten eines Watermarks gestartet, aber nicht im
  normalen Trackwechsel abgewartet.
- Nur wenn die Queue wirklich leer ist, darf der Wechsel auf eine Serverantwort
  warten.
- Ein `refillPromise` verhindert parallele doppelte Refills.
- Session-Token schützen weiterhin vor verspäteten Antworten eines alten
  Senders.

Empfohlene Queuegrößen:

- anfänglich 8 bis 10 Tracks laden
- bei 4 bis 5 verbleibenden Tracks im Hintergrund nachladen
- mindestens 2 Tracks müssen jederzeit fest bestimmt sein

### Preload robuster machen

- Preload starten, sobald der nächste Track feststeht.
- Im Slot die erwartete Track-ID speichern.
- Veraltete `canplay`-, `progress`- oder Fehler-Callbacks ignorieren.
- Vor dem Crossfade die gepufferte Dauer prüfen:

```javascript
function bufferedAhead(element) {
  if (!element.buffered.length) return 0;
  return element.buffered.end(element.buffered.length - 1) - element.currentTime;
}
```

- Empfohlener Mindestwert vor Fade-Beginn: `CF_IN + 3` Sekunden.
- Wenn der Puffer am geplanten Startpunkt nicht ausreicht, den ausgehenden Track
  nicht vorsorglich leiser machen.

### Aufwand und Nutzen

- Aufwand: ungefähr 1 bis 2 Entwicklungstage inklusive Tests
- Risiko: niedrig bis mittel
- erwarteter Nutzen: Beseitigung des größten Teils der Browserpausen
- zusätzlicher Cache ist hierfür nicht zwingend erforderlich

## Strategie B: Plattformübergreifender Cache und kontrolliertes Preloading

Diese Strategie schützt zusätzlich gegen WLAN-Schwankungen, langsame
NAS-Zugriffe und Serverlast.

### Server

Stream-URLs sollten eine Inhaltsversion enthalten, zum Beispiel:

```text
/api/stream/123?v=<mtime_ns>-<size>
```

Alternativ kann ein beim Scan berechneter Content-Hash verwendet werden. Alle
Clients müssen dieselbe Version aus den Trackmetadaten erhalten.

Für vollständige und partielle Antworten sollten konsistent gesetzt werden:

- `ETag`
- `Last-Modified`
- `Accept-Ranges: bytes`
- `Cache-Control`
- korrekte `Content-Length`- und `Content-Range`-Werte

Nur eine tatsächlich versionierte URL sollte langfristig als `immutable`
markiert werden.

Für das Docker-Deployment sollte geprüft werden, ob Audiodateien nach der
Pfadauflösung durch Flask über Nginx beziehungsweise `X-Accel-Redirect`
ausgeliefert werden können. Dadurch bleiben Gunicorn-Threads für API-Anfragen
frei. Der interne Pfad muss streng auf `MUSIC_ROOT` begrenzt bleiben.

### Browser

- Strategie A bleibt notwendig; HTTP-Cache ersetzt keinen atomaren Handoff.
- Den nächsten Track unmittelbar nach der Queue-Entscheidung laden.
- Versionierte URLs erlauben Browser-Disk-Cache und sichere Wiederverwendung.
- Ein Service Worker mit vollständigem Audio-LRU-Cache ist nur als spätere
  Option sinnvoll. Range-Anfragen und große FLAC-Dateien machen ihn deutlich
  komplexer als normalen Asset-Cache.

### Android

Empfohlene Media3-Komponenten:

- `SimpleCache` als Singleton
- `LeastRecentlyUsedCacheEvictor`, beispielsweise 256 bis 512 MB
- `StandaloneDatabaseProvider`
- `CacheDataSource.Factory`
- dieselbe DataSource für Wiedergabe und Preloading
- nach Media3-Upgrade ein `DefaultPreloadManager`

Der Cache-Key muss mindestens Track-ID und Inhaltsversion enthalten. Eine
alleinige Track-ID kann nach einem Dateiaustausch veraltete Bytes liefern.

Zusätzlich sollte Android mehrere Trackmetadaten in einem Request abrufen,
anstatt `count=1` für jeden einzelnen Folgetrack zu verwenden. Eine lokale Queue
von 3 bis 5 Tracks reduziert API-Latenz und macht manuelles Überspringen
robuster.

Ein angepasstes `DefaultLoadControl` kann größere zeitbasierte Puffergrenzen und
die Priorisierung von Zeit gegenüber Byte-Schwellen verwenden. Die Werte müssen
mit FLAC und MP3 auf realen Geräten getestet werden; ein größerer Puffer erhöht
Speicher-, Netz- und Energieverbrauch.

### Aufwand und Nutzen

- Aufwand: ungefähr 3 bis 5 Entwicklungstage
- Risiko: mittel
- erwarteter Nutzen: robuste gapless Übergänge und schnelle manuelle Wechsel
- Einschränkung: erzeugt allein noch keinen echten Android-Crossfade

## Strategie C: Echter Crossfade auf Android

Wenn eine hörbare Überblendung auch in der nativen App zwingend ist, werden zwei
parallele Decode-Pipelines benötigt.

### Vorgeschlagener Aufbau

- Zwei ExoPlayer-Instanzen: aktiver und vorbereiteter Player.
- Beide verwenden denselben `SimpleCache` und dieselbe CacheDataSource.
- Der nächste Player wird vollständig vorbereitet, bleibt aber pausiert und bei
  Lautstärke null.
- `CF_IN` Sekunden vor dem Ende startet der nächste Player.
- Beide Lautstärken folgen einer Equal-Power-Kurve.
- Nach dem Fade werden die Rollen getauscht und der alte Player vorbereitet.
- Nach außen existiert weiterhin genau eine MediaSession.
- Audiofokus, WakeLock, Notification und Telemetrie werden zentral durch den
  Service koordiniert und nicht unabhängig von beiden Playern verwaltet.

Die frühere problematische Dual-MediaPlayer-Lösung sollte nicht wiederbelebt
werden. Falls dieser Weg gewählt wird, sollte er mit zwei ExoPlayern, gemeinsamem
Cache und einem expliziten Zustandsautomaten umgesetzt werden.

### Zu testende Android-Sonderfälle

- Pause oder manueller Trackwechsel während eines aktiven Fades
- Bluetooth-Verbindungswechsel
- eingehender Anruf und Verlust des Audiofokus
- Kopfhörer werden entfernt
- App im Hintergrund oder Display ausgeschaltet
- Android Auto verbindet oder trennt sich
- Service-Neustart während des Preloads
- Netzwerkverlust während des Fades
- unterschiedliche Codecs und Sample-Raten

### Aufwand und Nutzen

- Aufwand: ungefähr 5 bis 10 Entwicklungstage
- Risiko: mittel bis hoch
- Nutzen: echter Crossfade statt nur gapless Wiedergabe
- Kosten: zwei Decoder, mehr Speicher, Energie und Netzwerkaktivität

## Alternative: Serverseitig gerenderter Radiostream

Für einen ausschließlich radioartigen Anwendungsfall könnte der Server die
Trackfolge samt Crossfade über FFmpeg oder Liquidsoap als kontinuierlichen
Stream rendern. Der Client hätte dann nur eine Audioquelle, und Trackgrenzen
könnten keine clientseitigen Ladepausen mehr erzeugen.

Diese Architektur ist für Adolar aber nur eine langfristige Alternative:

- manuelles Überspringen wird träger oder erfordert einen neuen Stream
- individuelle Benutzerqueues benötigen eigene Streamprozesse
- Metadaten, Scrobbling und Favoriten müssen separat synchronisiert werden
- Transcoding kostet CPU und kann verlustbehaftet sein
- HLS würde zusätzliche Segmentlatenz erzeugen

Sie ist daher nicht die empfohlene erste Maßnahme.

## Empfohlene Umsetzungsreihenfolge

### Phase 1: Messbarkeit

Vor oder gemeinsam mit dem ersten Fix folgende Zeitpunkte protokollieren:

Browser:

- Preload-URL gesetzt
- `loadedmetadata`, `canplay`, `canplaythrough`, `waiting`, `stalled`, `error`
- gepufferte Sekunden bei Crossfade-Beginn
- Auflösung des `play()`-Promises
- Beginn und Ende des Handoffs
- Dauer jedes Queue-Refills
- Stream-TTFB über Resource Timing, soweit verfügbar

Android:

- API-Anfrage für nächste Tracks
- MediaSource hinzugefügt
- Load-Start und Load-Ende
- gepufferte Dauer
- `STATE_BUFFERING` und `STATE_READY`
- MediaItem-Transition
- Rebuffer-Dauer

Backend:

- Dauer der Queue-Endpunkte
- Dauer bis zum ersten Audiobyte
- Status und Range der Stream-Anfrage
- gleichzeitig aktive Streamantworten

### Phase 2: Browser-Fix

1. Hauptplayer auf austauschbare aktive/inaktive Audioelemente umbauen.
2. Erfolgreichen Crossfade ohne `src`-Neuzuweisung abschließen.
3. Queue-Refill aus dem kritischen Trackwechselpfad entfernen.
4. Preload früher starten und Track-ID validieren.
5. Pufferdauer statt nur `readyState` prüfen.

### Phase 3: Backend und Android-Cache

1. Inhaltsversion in Stream-URLs aufnehmen.
2. Range- und Cache-Header vereinheitlichen.
3. Optional Nginx-Offload ergänzen.
4. Media3 aktualisieren und Regressionstests durchführen.
5. Android-SimpleCache und CacheDataSource einführen.
6. Android-Trackqueue und PreloadManager ergänzen.

### Phase 4: Android-Crossfade-Entscheidung

Nach Messung der gapless Übergänge entscheiden:

- Wenn praktisch keine Pausen mehr hörbar sind, beim einzelnen ExoPlayer
  bleiben.
- Wenn echte Überblendung Produktanforderung ist, Dual-ExoPlayer-Zustandsautomat
  implementieren.

## Abnahmekriterien

Mindestens folgende Szenarien sollten automatisiert oder manuell geprüft werden:

### Browser

- 20 automatische Trackwechsel in Radio ohne hörbare Stille
- 20 Trackwechsel in Playlist/Shuffle mit aktiviertem Crossfade
- kein zweiter Request für denselben Folgetrack beim erfolgreichen Handoff
- Queue-Refill blockiert weder Audio noch UI
- manueller Next-Klick während Preload und während Crossfade
- Wechsel des Radiosenders während Preload und während Crossfade
- Tab im Hintergrund und erneute Aktivierung
- MP3, FLAC, M4A, OGG/Opus und AAC, soweit Testdateien vorhanden sind

### Android

- 20 automatische Trackwechsel bei eingeschaltetem Display
- 20 automatische Trackwechsel bei ausgeschaltetem Display
- Android Auto verbunden und getrennt
- manuelles Next bei vorbereitetem und nicht vorbereitetem Folgetrack
- simulierte langsame oder kurz unterbrochene Verbindung
- Cache-Hit nach erneutem Abspielen desselben Tracks
- keine doppelte MediaSession und kein verlorener Audiofokus

### Zielwerte

- gapless Modus: P95 der hörbaren Stille unter 100 ms im lokalen Netzwerk
- Crossfade-Modus: keine unbeabsichtigte Stille zwischen den Tracks
- kein Trackwechsel wartet auf einen normalen Queue-Refill
- kein erfolgreicher Browser-Crossfade öffnet den Folgetrack beim Handoff neu
- Android meldet keine unnötigen `STATE_ENDED`-Fallbacks bei gefüllter Queue

## Tests und technische Schulden

Die vorhandenen Python-Streamingtests prüfen Statuscodes, Content-Type und
grundlegende Range-Antworten, aber noch keine Cache-Header oder Conditional-
Requests. Diese Tests sollten erweitert werden.

Für die Browser-Playback-Logik existieren derzeit keine erkennbaren
automatisierten Tests. Empfehlenswert ist, die Zustandslogik in einen kleinen,
DOM-unabhängigen Controller auszulagern und diesen mit Unit-Tests zu versehen.
Zusätzlich können Playwright-Tests zwei instrumentierte Audioelemente und einen
verzögerten Testserver verwenden.

Beim Erstellen dieses Dokuments ließen sich die vorhandenen Streamingtests lokal
nicht ausführen:

- `.venv` verweist auf ein nicht mehr vorhandenes `C:\Python314\python.exe`.
- Dem aktuell gefundenen System-Python fehlen Projektabhängigkeiten wie
  `psutil` und `pytest`.

Vor der Implementierung sollte die lokale virtuelle Umgebung deshalb neu
aufgebaut werden.

## Startprompt für einen neuen Codex-Task

```text
Lies docs/playback-refactor.md vollständig. Implementiere zunächst ausschließlich
Phase 1 und Phase 2: Instrumentierung, atomarer Audioelement-Handoff im
Haupt-Webplayer, nicht blockierender Radio-Queue-Refill, frühes Track-ID-
validiertes Preloading und Prüfung der tatsächlich gepufferten Dauer. Verwende
templates/radio.html als Referenz für das Tauschen der aktiven Audioelemente.
Verändere Android und die Stream-API in diesem Schritt noch nicht. Bewahre
vorhandene uncommittete Änderungen, ergänze passende Tests und dokumentiere die
gemessenen Übergangszeiten.
```

## Externe technische Referenzen

- Android Media3 PreloadManager:
  https://developer.android.com/media/media3/exoplayer/preloading-media/preloadmanager
- Android Media3 Caching und Network Stacks:
  https://developer.android.com/media/media3/exoplayer/network-stacks
- `CacheDataSource`:
  https://developer.android.com/reference/androidx/media3/datasource/cache/CacheDataSource
- `SimpleCache`:
  https://developer.android.com/reference/androidx/media3/datasource/cache/SimpleCache
- `DefaultLoadControl`:
  https://developer.android.com/reference/androidx/media3/exoplayer/DefaultLoadControl
- Web Audio API:
  https://www.w3.org/TR/webaudio-1.0/
