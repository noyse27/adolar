# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projekt

Adolar ist eine selbst gehostete Musikarchiv-Webapp (Flask/Python-Backend,
Vanilla-JS-Frontend) für Synology NAS/Docker: durchsuchbare lokale
MP3/FLAC/M4A-Bibliothek, Streaming im Browser, Playlists, Smart Shuffle,
konfigurierbare Radiostationen mit Crossfade, Mehrbenutzer-Auth mit
Capability-basierten Rechten, Last.fm-Anbindung, Lyrics, Backups u.v.m. —
siehe `README.md` für die vollständige Feature-/API-/Env-Referenz. Dazu gehören
eine Android-App (`adolar-android/`, inkl. Android Auto) und ein Windows-
Companion-Wrapper (`companion/`).

`DESIGN_SPEC.md` beschreibt das abgestimmte Web-UI-Layout verbindlich — bei
Frontend-Änderungen an `templates/index.html`/`static/css/main.css`
gegenprüfen statt frei zu improvisieren.

## Befehle

**Python-Backend** (lokale venv verwenden, nicht global installierte Python):
```powershell
.\.venv\Scripts\python.exe -m pytest -q                    # komplette Suite
.\.venv\Scripts\python.exe -m pytest tests\test_db_misc.py -q   # eine Testdatei
.\.venv\Scripts\python.exe -m pytest tests\test_db_misc.py -k test_name -q  # ein Test
.\.venv\Scripts\ruff.exe check .                            # Lint (S/bandit, I, UP, B aktiv)
```
CI (`.github/workflows/ci.yml`) führt bei jedem Push/PR auf `main` exakt
`ruff check .` und `pytest -q` aus — beides vor größeren Änderungen lokal
laufen lassen. Ruff-Version ist auf `0.16.0` gepinnt (muss mit `pyproject.toml`
übereinstimmen).

**App lokal starten:**
```bash
python run.py        # liest .env, fragt MUSIC_ROOT interaktiv ab falls ungesetzt
# oder: docker compose up -d
```

**JavaScript:** kein Build-Schritt, mindestens Syntax prüfen:
```powershell
node --check static\js\app.js
```

**Android** (`adolar-android/`):
```powershell
cd adolar-android
.\gradlew.bat testDebugUnitTest assembleDebug --console=plain
```
Nach dem Build prüfen, dass APK und kompilierte Klassen aktuell sind; bei
nachweislich veraltetem Gradle-Artefakt einmal mit `--rerun-tasks` wiederholen.
Debug-APK: `adolar-android\app\build\outputs\apk\debug\app-debug.apk`. Auf
dieser Maschine: Android Studio unter
`C:\Users\noyse\AppData\Local\Programs\Android Studio`, SDK unter
`C:\Users\noyse\AppData\Local\Android\Sdk`, ADB dort unter
`platform-tools\adb.exe` (nicht zwingend in `PATH`). Installation ohne
App-Daten zu löschen:
```powershell
& "C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe" install -r `
  "F:\claude\musicapp\adolar-android\app\build\outputs\apk\debug\app-debug.apk"
```
Die APK nur nach ausdrücklicher Freigabe des Nutzers auf ein Gerät übertragen.

**Windows Companion** (`companion/`, PyInstaller-Wrapper):
```powershell
.\.venv\Scripts\python.exe -m py_compile companion\adolar_radio.py   # Syntax-Check
cd companion && .\build.bat                                          # nur bei Änderungen unter companion/
```
Der Companion lädt `/radio` vom laufenden Adolar-Server — Änderungen an
`templates/radio.html` brauchen deshalb **keinen** neuen EXE-Build.

## Architektur

**Ein monolithischer Flask-App-Prozess**, keine Blueprints: praktisch alle
Routen liegen direkt in `app.py` (~3100 Zeilen). Die gesamte SQL-Schicht liegt
in `db.py` (~2300 Zeilen). Unterstützende Module am Root sind fachlich
geschnitten: `auth.py` (Sessions, Brute-Force-Schutz), `scanner.py`
(Bibliotheks-Indexierung), `lyrics.py`, `smart_shuffle.py`, `backup_service.py`,
`tasks.py` (Registry für Background-Jobs: Scan, BPM, Thumbnails, Backups),
`lastfm.py`, `libraries.py`/`library_context.py` (Multi-Library, siehe unten),
`errors.py`. `adolar4u/` ist das private, dark-gelaunchte Personalisierungs-
Lernmodul (siehe `docs/adolar4u*.md`).

**Zwei-Datenbank-Design:** Jede Anfrage nutzt eine Content-DB (Tracks, Covers,
Playlists, Radiostationen — pro Bibliothek austauschbar) plus eine über
`ATTACH DATABASE ... AS control` fest angehängte Control-DB (Users, Sessions,
Audit-Log, API-Tokens — bleibt beim Wechseln der aktiven Bibliothek
unverändert, sonst würden Accounts beim Library-Wechsel ausgesperrt). Tabellen-
namen kollidieren zwischen beiden Schemas nie, daher brauchen die meisten
Queries kein Schema-Präfix; `control.`-Tabellen werden in `db.py` explizit
qualifiziert. `db.get_connection()` registriert außerdem zwei eigene SQL-
Funktionen: `ALBUM_DIR` (gruppiert Compilations über den Ordnerpfad, da es
keinen separaten Album-Artist-Tag im Schema gibt) und `ULOWER` (casefold statt
ASCII-only `LOWER()`, für nicht-lateinische Suche).

**Multi-Library:** `libraries.py` hält eine kleine JSON-Registry (Pfad +
DB-Datei je Bibliothek) außerhalb jeder Content-DB. `library_context.py`
bindet die aktive Bibliothek pro Request als `contextvars`-Snapshot — nötig,
weil Gunicorns `gthread`-Worker Threads über Requests hinweg teilen und
mutable Modul-Globals dabei race-anfällig wären. Background-Threads erben den
zum Startzeitpunkt aktiven Snapshot explizit (`library_context.wrapped`).

**Schema-Migrationen:** kein Versionierungs-Framework. Additive Änderungen
werden als `ALTER TABLE ... ADD COLUMN`-Strings in die Liste in `db.init_db()`
eingetragen und dort reihum in `contextlib.suppress(Exception)` ausgeführt
(idempotent, da ein Fehler bei bereits vorhandener Spalte einfach verschluckt
wird). Für neue Spalten dort ergänzen statt ein eigenes Migrationssystem zu
bauen. Strukturellere Änderungen (z. B. Wegfall eines Foreign Keys) laufen
über Rename-Recreate-Copy-Drop, siehe `rebuild_table_dropping_user_fk()` als
Muster.

**Fehler-Konvention:** `errors.ValidationError` trägt eine kuratierte,
deutschsprachige, nutzersichere Nachricht (`.user_message`), die 1:1 in
API-Antworten darf. Ein einfacher `ValueError` ist für interne
Programmierfehler und darf nie über `str(exc)` an den Client durchsickern
(CodeQL `py/stack-trace-exposure`).

## Player-Verhalten über mehrere Oberflächen

Änderungen an Play/Pause, Zurück/Weiter, Queue, Crossfade, Radio oder
Telemetrie betreffen mehrere unabhängige Implementierungen — bei
Verhaltensänderungen alle vier prüfen:

1. Android-App & Android Auto: `adolar-android/app/src/main/java/net/polze/adolarradio/AdolarMediaService.java`
2. Webplayer: `static/js/app.js`
3. Radio Companion/Web-Radio: `templates/radio.html`
4. Miniplayer-Kommandos: `templates/miniplayer.html`

## Tests

Kein `conftest.py` — jedes Testmodul setzt `DB_PATH`/`CONTROL_DB_PATH` per
`os.environ.setdefault(...)` auf ein temporäres Verzeichnis, **bevor** `app`
importiert wird (der Modul-Import erzeugt bereits die Flask-App und öffnet
DB-Verbindungen). Pro Test patcht `setUp()` zusätzlich `db.DB_PATH` /
`db.CONTROL_DB_PATH` auf ein frisches Temp-Verzeichnis und ruft
`db.init_db()` — neue Testdateien sollten dieses Muster übernehmen (siehe
z. B. `tests/test_app_pages_and_search.py`). `pyproject.toml` setzt
`pythonpath = ["."]`, damit `pytest` unabhängig vom Aufrufverzeichnis aus dem
Repo-Root importiert.

`tests/*` ist in der Ruff-Konfiguration gezielt von `S101`/`S105`/`S106`/
`S311`/`E402` ausgenommen (Asserts, Test-Zugangsdaten, geseedeter `random`,
Env-Setup vor Imports).

## Sonstiges

- `hilfe/manual.html` ist die Quelle des deutschen Nutzerhandbuchs (unter
  `/hilfe/manual.html` ausgeliefert) — bei sichtbaren Verhaltensänderungen
  mit prüfen, ob es angepasst werden muss.
- `docs/` enthält laufende Roadmaps/Architektur-Notizen, u. a.
  `adolar4u.md`/`adolar4u-roadmap.md`/`adolar4u-testing.md` (Adolar4U),
  `lyrics-roadmap.md`, `radio-stations.md`, `ui-bereiche.md` und `backlog.md`
  (unpriorisierte, aktuell blockierte Ideen).
- `tools/lrclib-windows-tray/` ist ein eigenständiges PowerShell-Tray-Tool,
  kein Teil der Flask-App.
