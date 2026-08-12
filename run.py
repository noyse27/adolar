"""Bare-metal launcher for Adolar (no Docker).

Loads config from a local .env file (real environment variables always
win), asks once for the one setting with no safe guessable default
(MUSIC_ROOT), then starts the same production server Docker uses.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

GUNICORN_ARGS = [
    "gunicorn",
    "--bind", "0.0.0.0:5000",
    "--worker-class", "gthread",
    "--workers", "2",
    "--threads", "4",
    "--timeout", "60",
    "--graceful-timeout", "30",
    "--keep-alive", "5",
    "wsgi:app",
]


def load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def prompt_for_music_root() -> None:
    if os.environ.get("MUSIC_ROOT"):
        return
    print("MUSIC_ROOT ist nicht gesetzt (weder als Umgebungsvariable noch in .env).")
    while True:
        answer = input("Pfad zur Musikbibliothek: ").strip().strip('"')
        if os.path.isdir(answer):
            break
        print(f"'{answer}' ist kein vorhandener Ordner. Bitte erneut versuchen.")
    os.environ["MUSIC_ROOT"] = answer
    with open(ENV_PATH, "a", encoding="utf-8") as f:
        f.write(f"MUSIC_ROOT={answer}\n")
    print(f"Gespeichert in {ENV_PATH} — beim nächsten Start nicht mehr nötig.")


def main() -> None:
    load_dotenv(ENV_PATH)
    prompt_for_music_root()

    if sys.platform == "win32":
        print(
            "Hinweis: Gunicorn läuft nicht unter Windows. Adolar startet mit dem "
            "Flask-Entwicklungsserver (nicht für unbeaufsichtigten Dauerbetrieb geeignet)."
        )
        from adolar import application as adolar_app
        adolar_app.app.run(host="0.0.0.0", port=5000, debug=False)  # noqa: S104
        return

    os.execvp(GUNICORN_ARGS[0], GUNICORN_ARGS)  # noqa: S606


if __name__ == "__main__":
    main()
