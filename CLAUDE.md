# Lokale Entwicklungsumgebung

## Webplayer / Docker Dev-Deploy

Für den lokalen Adolar-Webplayer ist die aktive Dev-Deployment-Instanz
`adolar-local` auf Port `15002`. Beim Neu-Deployen im Dev-Kontext immer die
lokale Compose-Datei und denselben Projektname verwenden, damit die bestehenden
lokalen Volumes erhalten bleiben:

```powershell
docker compose -p adolar-local -f docker-compose.local.yml up -d --build adolar
```

Nach dem Start den Healthcheck prüfen:

```powershell
Invoke-RestMethod -Uri http://localhost:15002/health
docker compose -p adolar-local -f docker-compose.local.yml ps
```

## Android

- Android Studio: `C:\Users\noyse\AppData\Local\Programs\Android Studio`
- Android SDK: `C:\Users\noyse\AppData\Local\Android\Sdk`
- ADB: `C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- Android-Projekt: `F:\claude\musicapp\adolar-android`
- Debug-APK: `F:\claude\musicapp\adolar-android\app\build\outputs\apk\debug\app-debug.apk`

Unter PowerShell ADB über den vollständigen Pfad aufrufen, da es nicht zwingend in
`PATH` eingetragen ist. Die Debug-App kann ohne Löschen der App-Daten so aktualisiert
werden:

```powershell
& "C:\Users\noyse\AppData\Local\Android\Sdk\platform-tools\adb.exe" install -r "F:\claude\musicapp\adolar-android\app\build\outputs\apk\debug\app-debug.apk"
```
