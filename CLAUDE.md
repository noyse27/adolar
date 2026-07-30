# Lokale Entwicklungsumgebung

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

