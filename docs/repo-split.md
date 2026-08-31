# Repo-Split: Android und Companion

Ziel: `adolar-android` und `companion` werden als eigenstaendige Repositories
gefuehrt, behalten aber ihren bisherigen Git-Verlauf aus dem Monorepo.

## Vorbereitung im Monorepo

- Beide Unterprojekte enthalten eigene CI-Workflows unter `.github/workflows/ci.yml`.
- Beide Unterprojekte enthalten eigene Hygiene-/Agent-Dateien (`AGENTS.md`, `CLAUDE.md`).
- `adolar-android/gradle/wrapper/gradle-wrapper.jar` muss beim Split versioniert
  werden. Der Wrapper-JAR ist fuer frische CI-Checkouts erforderlich.

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

## Nach dem Push

- In `adolar-android` pruefen: `./gradlew testDebugUnitTest lintDebug assembleDebug`.
- In `adolar-companion` pruefen: `python -m ruff check .`, `python -m py_compile adolar_radio.py make_icon.py`, `python -m PyInstaller adolar_radio.spec --clean --noconfirm`.
- GitHub Actions in beiden neuen Repositories einmal manuell durch einen PR oder Push ausloesen.
- Danach im Monorepo entscheiden, ob die Unterordner entfernt oder als Submodule/Subtrees ersetzt werden sollen.
