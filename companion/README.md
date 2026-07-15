# AdolarRadio – Windows Companion App

Öffnet den Adolar Radio-Modus in einem nativen Windows-Fenster — kein Browser nötig.

## Voraussetzungen

- Python 3.10+
- Windows 10/11 (WebView2 ist vorinstalliert)
- Adolar läuft auf dem NAS (oder lokal)

## Starten (ohne Build)

```bat
pip install pywebview
python adolar_radio.py --host 192.168.1.X --port 15002
```

## Als .exe bauen

```bat
build.bat
```

Die fertige `AdolarRadio.exe` liegt danach in `dist\`.

## Host konfigurieren

```bat
AdolarRadio.exe --host 192.168.1.X --port 15002
```

Standardwert: `localhost:15002`

Alternativ kann die Server-URL direkt im Zahnrad-Menü eingetragen werden. Nach der
Verbindung ist dort optional eine Anmeldung mit dem Adolar-Benutzerkonto möglich;
Verbindungs- und Anmeldestatus werden für den nächsten Start gespeichert.
