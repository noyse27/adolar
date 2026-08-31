import atexit
import logging
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, request
from flask_cors import CORS

from . import auth as _auth
from . import (
    db,
    libraries,
    library_context,
    lyrics,
)
from .routes import (
    flush_play_count_tags,
    register_blueprints,
    run_scheduled_backup,
    start_lyrics_startup_scan,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    static_folder=os.path.join(PROJECT_ROOT, "static"),
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)
APP_VERSION = "1.9.0"

# Restrict CORS to origins defined via env var (space-separated).
# Default: deny all cross-origin requests (safe for local NAS use).
_cors_origins = os.environ.get("CORS_ORIGINS", "")
CORS(app, origins=_cors_origins.split() if _cors_origins else [])

if _auth.DEV_ADMIN_ENABLED:
    logging.getLogger(__name__).warning(
        "ADOLAR_DEV_ADMIN is active: every request runs as 'dev-admin' without "
        "authentication. Never enable this in production."
    )

MUSIC_ROOT = os.environ.get("MUSIC_ROOT", "/music")
MAX_DOWNLOAD_IDS = int(os.environ.get("MAX_DOWNLOAD_IDS", 500))
DATA_ROOT = os.path.dirname(os.path.abspath(os.path.expanduser(
    os.environ.get("DB_PATH", "") or "~/.cache/adolar.db"
)))
JINGLE_ROOT = os.path.join(DATA_ROOT, "radio_jingles")
LIBRARY_REGISTRY_PATH = os.path.join(DATA_ROOT, "libraries.json")
LIBRARIES_DIR = os.path.join(DATA_ROOT, "libraries")
# Anchored to DATA_ROOT (not left on db.py's own "/data/adolar.db" default)
# so a bare-metal run (no DB_PATH env var) writes next to DATA_ROOT's own
# fallback instead of silently trying the Docker-only "/data/adolar.db".
db.DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA_ROOT, "adolar.db")
# Anchored to DATA_ROOT (not left on db.py's own "/data/control.db" default)
# so it sits next to whichever DB_PATH was configured. Library switches only
# change request-local content snapshots; the control path always stays put.
db.CONTROL_DB_PATH = os.environ.get("CONTROL_DB_PATH") or os.path.join(DATA_ROOT, "control.db")
BACKUP_TIMEZONE = os.environ.get("TZ", "Europe/Berlin")


def _current_music_root() -> str:
    return library_context.music_root(MUSIC_ROOT)


def _active_library_snapshot() -> dict:
    """Read the registry's shared active-library state."""
    return libraries.get_active(LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH)


@app.before_request
def _bind_request_library():
    # Take one stable snapshot before auth or route code opens a database.
    # Other Gunicorn workers observe a switch through the shared registry on
    # their next request, while requests already in flight stay on their
    # original library instead of mixing two databases.
    active = _active_library_snapshot()
    manager = library_context.bind(active["db_path"], active["music_path"])
    manager.__enter__()
    g.library = active
    g.library_context_manager = manager


@app.teardown_request
def _unbind_request_library(_error=None):
    manager = g.pop("library_context_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)


# Authentication queries must run after the request's library snapshot is
# bound because every connection attaches control.db to a content database.
app.before_request(_auth.before_request)


def _start_library_thread(target, *, args=(), name: str | None = None):
    """Start a daemon thread pinned to the caller's current library."""
    db_path, root = library_context.snapshot(db.DB_PATH, MUSIC_ROOT)
    thread = threading.Thread(
        target=library_context.wrapped(target, db_path, root),
        args=args,
        daemon=True,
        name=name,
    )
    thread.start()
    return thread


# Seed defaults for the first run only; after that the admin-editable values
# in the settings table (see _backup_*() below) take over. This lets the
# schedule and destination be changed at runtime from the Datenbank-Wartung
# UI without a container restart.
_BACKUP_DEFAULT_RETENTION = max(1, int(os.environ.get("BACKUP_RETENTION", "7")))
_BACKUP_DEFAULT_HOUR = max(0, min(23, int(os.environ.get("BACKUP_HOUR", "3"))))
_BACKUP_DEFAULT_AUTO_ENABLED = os.environ.get("BACKUP_AUTO_ENABLED", "0").lower() in (
    "1", "true", "yes", "on",
)
# Docker-only path; bare-metal runs should set BACKUP_PATH (or change it
# afterward via the Datenbank-Wartung UI, see _backup_root() below).
_BACKUP_DEFAULT_ROOT = os.environ.get("BACKUP_PATH", "/backups")


def _backup_auto_enabled() -> bool:
    value = db.get_setting("backup_auto_enabled")
    return _BACKUP_DEFAULT_AUTO_ENABLED if value is None else value == "1"


def _backup_hour() -> int:
    value = db.get_setting("backup_hour")
    return _BACKUP_DEFAULT_HOUR if value is None else int(value)


def _backup_retention() -> int:
    value = db.get_setting("backup_retention")
    return _BACKUP_DEFAULT_RETENTION if value is None else int(value)


def _backup_root() -> str:
    value = db.get_setting("backup_root")
    return _BACKUP_DEFAULT_ROOT if value is None else value

# ── Adolar Disco connection tracking ─────────────────────────────────────────
_disco_last_seen: float = 0   # epoch seconds
_DISCO_TIMEOUT = 120          # seconds until considered disconnected

def _touch_disco():
    global _disco_last_seen
    _disco_last_seen = _time.time()


# Non-critical Last.fm telemetry must never hold a web request open during a
# network timeout. The executor and queue are deliberately small per Gunicorn
# worker so an outage cannot create an unbounded backlog.
_lastfm_executor = None
_lastfm_executor_lock = threading.Lock()
_lastfm_task_slots = threading.BoundedSemaphore(12)


def _get_lastfm_executor():
    global _lastfm_executor
    if _lastfm_executor is None:
        with _lastfm_executor_lock:
            if _lastfm_executor is None:
                _lastfm_executor = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="adolar-lastfm",
                )
    return _lastfm_executor


def _submit_lastfm_call(label: str, func, *args, retries: int = 0, **kwargs) -> bool:
    if not _lastfm_task_slots.acquire(blocking=False):
        logging.getLogger(__name__).warning(
            "Last.fm %s skipped: background queue is full", label,
        )
        return False

    def run():
        try:
            for attempt in range(max(0, int(retries)) + 1):
                try:
                    func(*args, **kwargs)
                    return
                except Exception as exc:
                    if attempt >= retries:
                        logging.getLogger(__name__).warning(
                            "Last.fm %s failed (%s): %s",
                            label, type(exc).__name__, exc,
                        )
                    else:
                        _time.sleep(0.75)
        finally:
            _lastfm_task_slots.release()

    try:
        _get_lastfm_executor().submit(run)
        return True
    except RuntimeError:
        _lastfm_task_slots.release()
        return False


def _shutdown_lastfm_executor():
    if _lastfm_executor is not None:
        _lastfm_executor.shutdown(wait=False, cancel_futures=True)


atexit.register(_shutdown_lastfm_executor)

def _disco_active() -> bool:
    return (_time.time() - _disco_last_seen) < _DISCO_TIMEOUT


def _safe_path(path: str) -> str | None:
    """Resolve path and verify it stays within MUSIC_ROOT. Returns None if outside."""
    music_root = _current_music_root()
    if not os.path.isabs(path):
        path = os.path.join(music_root, path)
    real   = os.path.realpath(path)
    root   = os.path.realpath(music_root)
    if not real.startswith(root + os.sep) and real != root:
        return None
    return real


def _safe_data_path(path: str, root: str) -> str | None:
    real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if not real.startswith(root_real + os.sep) and real != root_real:
        return None
    return real


def _safe_next_url(raw) -> str:
    """Normalize a post-login redirect target to a same-origin path.

    Never validates and passes the raw value through -- it rebuilds the
    target from the parsed path instead. This rejects absolute URLs,
    protocol-relative "//host" targets (browsers collapse any number of
    leading slashes), and backslash variants (CodeQL py/url-redirection).
    """
    parsed = urlparse(str(raw or "/").replace("\\", "/"))
    if parsed.scheme or parsed.netloc:
        return "/"
    path = "/" + parsed.path.lstrip("/")
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _client_error(message: str, exc: Exception, status: int = 400):
    """Log the technical exception, return only a stable message to the client.

    Never put str(exc) into a response (CodeQL py/stack-trace-exposure):
    exception text can contain file paths, SQL fragments, or library internals.
    """
    logging.getLogger(__name__).warning("%s (%s)", message, exc)
    return jsonify({"error": message}), status


def _int_arg(name: str, default: int, min_val: int = None, max_val: int = None) -> int:
    try:
        v = int(request.args.get(name, default))
    except (ValueError, TypeError):
        v = default
    if min_val is not None:
        v = max(min_val, v)
    if max_val is not None:
        v = min(max_val, v)
    return v


register_blueprints(app)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

# The library registry is authoritative for which content database and music
# folder are active; it persists across restarts independently of db.DB_PATH,
# so a library switched-to in a previous run stays active after a restart.
_active_library = libraries.get_active(LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH)
db.DB_PATH = _active_library["db_path"]
MUSIC_ROOT = _active_library["music_path"]

db.init_db()
_auth.load_persisted_blocks()
if lyrics.enabled():
    start_lyrics_startup_scan()


def _play_count_tag_scheduler():
    """Flush pending archive counts once per local calendar day after 03:00."""
    import datetime
    while True:
        active = _active_library_snapshot()
        with library_context.bind(active["db_path"], active["music_path"]):
            now = datetime.datetime.now()
            if now.hour >= 3:
                job_key = f"play_count_tag_job:{now.date().isoformat()}"
                if db.claim_once(job_key):
                    flush_play_count_tags()
        _time.sleep(300)


threading.Thread(target=_play_count_tag_scheduler, daemon=True).start()


def _database_backup_scheduler():
    """Create one verified snapshot per local day after the configured hour.

    Runs unconditionally so that enabling/disabling or rescheduling via the
    Datenbank-Wartung UI takes effect on the next tick, without a restart.
    """
    import datetime
    while True:
        active = _active_library_snapshot()
        with library_context.bind(active["db_path"], active["music_path"]):
            if _backup_auto_enabled():
                now = datetime.datetime.now(ZoneInfo(BACKUP_TIMEZONE))
                if now.hour >= _backup_hour():
                    job_key = f"database_backup_job:{now.date().isoformat()}"
                    if db.claim_once(job_key):
                        run_scheduled_backup()
        _time.sleep(300)


threading.Thread(
    target=_database_backup_scheduler,
    daemon=True,
    name="adolar-backup-scheduler",
).start()

if __name__ == "__main__":
    # Dev fallback only; production runs Gunicorn in a container where
    # binding all interfaces is intended.
    app.run(host="0.0.0.0", port=5000, debug=False)  # noqa: S104
