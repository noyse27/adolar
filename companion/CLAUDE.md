# Adolar Radio Companion

Dieses Repository ist die eigenstaendige Windows-Companion-App fuer Adolar Radio.

## Entwicklung

- Python 3.10+ verwenden; CI laeuft mit Python 3.12 auf `windows-latest`.
- Vor Aenderungen an Releases lokal mindestens `python -m py_compile adolar_radio.py make_icon.py` und `python -m ruff check .` ausfuehren.
- Der Windows-Build laeuft ueber `python -m PyInstaller adolar_radio.spec --clean --noconfirm`.
- `build/`, `dist/`, `__pycache__/` und Tool-Caches bleiben unversioniert.

## Produktgrenze

Die App ist eine pywebview-Huelle fuer den Adolar-Radio-Modus. Server-Routen,
Templates und API-Vertraege bleiben im Adolar-Server-Repo und sollten dort
gegengetestet werden.
