# Repo-Split: Android und Companion

Ziel: `adolar-android` und `companion` wurden als eigenstaendige Repositories
aus dem Monorepo herausgeloest und behalten ihren bisherigen Git-Verlauf.

Neue Repositories:

- <https://github.com/noyse27/adolar-android>
- <https://github.com/noyse27/adolar-companion>

## Vorbereitung im Monorepo

- Beide Unterprojekte erhielten eigene CI-Workflows unter `.github/workflows/ci.yml`.
- Beide Unterprojekte erhielten eigene Hygiene-/Agent-Dateien (`AGENTS.md`, `CLAUDE.md`).
- `adolar-android/gradle/wrapper/gradle-wrapper.jar` muss beim Split versioniert
  sein. Der Wrapper-JAR ist fuer frische CI-Checkouts erforderlich.

## History-preserving Split

Vom Monorepo-Root aus:

```powershell
git subtree split --prefix=adolar-android -b split/adolar-android
git subtree split --prefix=companion -b split/adolar-companion
```

Danach die Ziel-Repositories anlegen und die Split-Branches pushen:

```powershell
git remote add adolar-android <ANDROID_REPO_URL>
git remote add adolar-companion <COMPANION_REPO_URL>

git push adolar-android split/adolar-android:main
git push adolar-companion split/adolar-companion:main
```

Falls die Ziel-Repositories bereits initialisiert wurden, vorher sicherstellen,
dass keine abweichende `main`-History existiert, oder bewusst per PR/import
zusammenfuehren.

## Durchgefuehrt

- `split/adolar-android` wurde als `main` nach `noyse27/adolar-android` gepusht.
- `split/adolar-companion` wurde als `main` nach `noyse27/adolar-companion` gepusht.
- Historische Release-Assets wurden in die neuen Repos uebertragen.
- Die Unterordner `adolar-android/` und `companion/` wurden anschliessend aus
  dem Server-Repo entfernt.

## Nach dem Push / Pflege

- In `adolar-android` pruefen: `./gradlew testDebugUnitTest lintDebug assembleDebug`.
- In `adolar-companion` pruefen: `python -m ruff check .`, `python -m py_compile adolar_radio.py make_icon.py`, `python -m PyInstaller adolar_radio.spec --clean --noconfirm`.
- GitHub Actions in beiden neuen Repositories durch PRs oder Pushes pruefen.
