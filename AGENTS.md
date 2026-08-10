# Projektanweisungen – Adolar

## Projektbereiche

- Backend: `app.py`, `db.py` und weitere Python-Module im Projektstamm
- Webplayer: `templates/index.html`, `static/js/app.js`, `static/css/main.css`
- Radio Companion-Webseite: `templates/radio.html`
- Windows-Companion-Wrapper: `companion/`
- Android-App und Android Auto: `adolar-android/`
- Tests: `tests/`

## Übergreifendes Player-Verhalten

Änderungen an Wiedergabefunktionen wie Play/Pause, Zurück, Weiter, Queue,
Crossfade, Radio und Telemetrie auf allen betroffenen Oberflächen prüfen:

1. Android-App und Android Auto:
   `adolar-android/app/src/main/java/net/polze/adolarradio/AdolarMediaService.java`
2. Webplayer: `static/js/app.js`
3. Radio Companion und Web-Radio: `templates/radio.html`
4. Miniplayer-Kommandos: `templates/miniplayer.html`

Der Windows Companion lädt `/radio` vom Adolar-Server. Änderungen an
`templates/radio.html` benötigen daher keinen neuen EXE-Build. Ein EXE-Build
ist nur bei Änderungen am Wrapper unter `companion/` erforderlich.

## Python und Backend

Die lokale virtuelle Umgebung verwenden:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

Bei kleinen Änderungen zunächst die passende Testdatei ausführen, anschließend
bei höherem Risiko die vollständige Testsuite.

## JavaScript

Mindestens die Syntax prüfen:

```powershell
node --check static\js\app.js
```

Bei Änderungen an eingebettetem JavaScript in HTML zusätzlich den betreffenden
Player im Browser beziehungsweise Companion testen.

## Android

- Android Studio: `C:\Users\noyse\AppData\Local\Programs\Android Studio`
- Android SDK: `C:\Users\noyse\AppData\Local\Android\Sdk`
- ADB: `C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- Android-Projekt: `adolar-android`
- Debug-APK: `adolar-android\app\build\outputs\apk\debug\app-debug.apk`

Build:

```powershell
cd adolar-android
.\gradlew.bat testDebugUnitTest assembleDebug --console=plain
```

Nach dem Build kontrollieren, dass APK und kompilierte Klassen aktuell sind.
Bei einem nachweislich veralteten Gradle-Artefakt den Build einmal mit
`--rerun-tasks` wiederholen.

Die APK nur nach ausdrücklicher Freigabe übertragen. Vorhandene App-Daten mit
`install -r` erhalten:

```powershell
& "C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe" install -r `
  "F:\claude\musicapp\adolar-android\app\build\outputs\apk\debug\app-debug.apk"
```

## Windows Companion

Wrapper prüfen:

```powershell
.\.venv\Scripts\python.exe -m py_compile companion\adolar_radio.py
```

Nur bei Änderungen unter `companion/` neu bauen:

```powershell
cd companion
.\build.bat
```

## Änderungsumfang

Bestehende, nicht zur Aufgabe gehörende Änderungen im Worktree bewahren. Bei
sichtbarem Verhalten auch Dokumentation und Hilfetexte auf notwendige
Anpassungen prüfen.
