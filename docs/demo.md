# Demomodus

Adolar kann als isolierte, öffentlich zugängliche Demo-Instanz betrieben
werden – zum Ausprobieren, ohne dass irgendwo eine echte Musikbibliothek,
echte Zugangsdaten oder dauerhafte Nutzerdaten entstehen.

## Was der Demomodus macht

- Die Datenbank wird periodisch (Standard: stündlich) vollständig
  zurückgesetzt: alle Accounts, Tracks, Playlisten, Radiosender,
  Verbindungs-/Audit-Logs und Last.fm-Verknüpfungen werden gelöscht und neu
  befüllt mit:
  - einem festen Demo-Admin-Account,
  - einem festen Demo-Hörer-Account,
  - einer kleinen, synthetisch erzeugten Musikbibliothek (zehn Fantasie-Songs
    über drei Fantasie-Künstler, mit echten ID3-Tags – siehe unten).
- Ein sichtbares Banner im Frontend weist auf den Demomodus hin und zeigt
  Admin- und Hörer-Zugangsdaten – beides ist bewusst kein Geheimnis, da die
  Instanz ohnehin nur Testdaten enthält und sich selbst zurücksetzt.
- Ein `X-Robots-Tag: noindex, nofollow`-Header verhindert, dass die
  Demo-Instanz in Suchmaschinen auftaucht.
- Eine Reihe destruktiver Admin-Aktionen ist gesperrt (Sicherung
  erstellen/löschen/konfigurieren, Bibliotheken anlegen/wechseln/verschieben/
  umbenennen, Datenbank-Optimierung) – siehe `adolar/demo_mode.py`s
  `block_when_demo()`, angewendet in `adolar/routes/admin.py`. Alles andere
  (Streaming, Suche, Playlisten, Radiosender, Benutzerverwaltung,
  Token-Ausgabe, Systemüberwachung) funktioniert normal.
- Kein `LASTFM_API_KEY`/`LASTFM_API_SECRET` gesetzt: eine öffentliche Demo
  soll niemals echte Last.fm-Scrobbles über den App-Schlüssel des Betreibers
  weiterleiten. Der „Last.fm verbinden“-Button bleibt sichtbar, schlägt aber
  serverseitig fehl, ohne dass dafür zusätzlicher Code nötig war.

## Aktivierung

Rein über die Umgebungsvariable `ADOLAR_DEMO_MODE=1`
(`adolar/demo_mode.py`), gesetzt für eine komplett separate
Compose-Installation – **niemals** gegen eine bestehende, echte Datenbank.

Am einfachsten über das mitgelieferte Setup-Skript, das `.env.demo` bei
Bedarf mit einem zufälligen `SECRET_KEY` anlegt und den Stack startet:

```bash
./setup.sh demo
```

Entspricht von Hand ausgeführt:

```bash
cp .env.demo.example .env.demo
# SECRET_KEY in .env.demo setzen (openssl rand -hex 32)

docker compose -p adolar-demo --env-file .env.demo -f docker-compose.demo.yml up -d --build
```

`./setup.sh` (ohne Argument oder mit `production`) macht dasselbe für die
normale Installation (`.env` statt `.env.demo`). Beide Aufrufe sind sicher
mehrfach ausführbar - eine bereits vorhandene Env-Datei bzw. ein bereits
gesetztes Secret wird nie überschrieben.

`docker-compose.demo.yml` ist bewusst eine eigenständige Compose-Datei, kein
Override der normalen `docker-compose.yml` – sie hat einen eigenen
Standard-Port (`15012`, siehe `.env.demo.example`), ein eigenes Daten-Volume
(durch den Compose-Projektnamen `adolar-demo` automatisch von der echten
Installation getrennt) und einen zusätzlichen `demo-library`-Service, der
die Platzhalter-Musikbibliothek erzeugt, bevor Adolar startet. Eine echte
Adolar-Installation und eine Demo-Installation können so parallel auf
demselben Host laufen, ohne sich in die Quere zu kommen.

### Konfigurierbare Werte (`.env.demo`)

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `SECRET_KEY` | *(empfohlen)* | wie bei der echten Installation; ohne festen Wert verliert jeder Neustart alle Sitzungen |
| `ADOLAR_DEMO_RESET_MINUTES` | `60` | Reset-Intervall in Minuten, geklemmt auf 5–1440 |
| `ADOLAR_DEMO_ADMIN_USERNAME` / `_PASSWORD` | `demo-admin` / `adolar-demo` | fester Admin-Login, auf dem Banner sichtbar |
| `ADOLAR_DEMO_USER_USERNAME` / `_PASSWORD` | `demo-hoerer` / `adolar-demo` | fester Hörer-Login, auf dem Banner sichtbar |
| `DEMO_HOST_PORT` | `15012` | Host-Port, kollisionsfrei zur echten Installation (`15002`) |
| `TRACK_DEMO_CLIP_SECONDS` | `8` | Länge der generierten Platzhalter-Tracks |

## Die Platzhalter-Musikbibliothek

`demo/generate-library.sh` erzeugt beim ersten Start zehn kurze Sinuston-MP3s
über drei Fantasie-Künstler/-Alben (verschiedene Jahre/Genres, für eine
sinnvolle Suche/Filterung), jeweils mit echten ID3-Tags (Titel, Künstler,
Album, Genre, Jahr, Tracknummer) via `ffmpeg`. Es werden keine echten
Musikstücke verwendet oder mitgeliefert – das wäre sowohl ein
Urheberrechtsproblem als auch unnötig für eine öffentliche Demo. Der Scan
in die Datenbank läuft synchron beim Reset (`adolar/demo_mode.py`s
`_seed_demo_library()`, wiederverwendet `scanner._scan_file`), nicht über
den üblichen asynchronen Hintergrund-Scan.

## Sicherheitsmechanismus

`adolar/demo_mode.py`s `assert_demo_safe_to_manage()` läuft bei jedem Start,
wenn `ADOLAR_DEMO_MODE=1` gesetzt ist:

- Findet sie einen `demo_managed`-Setting-Eintrag, ist die Datenbank bereits
  als Demo-Instanz markiert – der periodische Reset läuft normal weiter.
- Ist die Datenbank leer (kein einziger Account), wird sie einmalig befüllt
  und der Marker gesetzt.
- Enthält die Datenbank bereits Accounts, aber **keinen** Marker, verweigert
  das Backend den Start mit einem Fehler. Das verhindert, dass ein
  Konfigurationsfehler (z. B. ein versehentlich wiederverwendeter `DB_PATH`)
  eine echte, befüllte Installation stillschweigend periodisch leerräumt.

## Tests

```bash
pytest tests/test_demo_mode.py -v
```

Deckt ab: Env-Var-Parsing (Aktivierung, Clamping von
`ADOLAR_DEMO_RESET_MINUTES`), Erstbefüllung, Idempotenz, Verweigerung bei
fremden Daten ohne Marker, Reset inklusive echtem Trailer-Scan (übersprungen,
falls kein `ffmpeg` verfügbar ist), die `block_when_demo`-Dekoration und den
öffentlichen `/api/demo/status`-Endpunkt.
