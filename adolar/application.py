import atexit
import contextlib
import hashlib
import html
import ipaddress
import json
import logging
import os
import sqlite3
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psutil
from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, send_file
from flask import session as flask_session
from flask_cors import CORS
from werkzeug.http import http_date
from werkzeug.utils import secure_filename

from . import (
    adolar4u,
    backup_service,
    db,
    errors,
    lastfm,
    libraries,
    library_context,
    lyrics,
    scanner,
    smart_shuffle,
    tasks,
)
from . import auth as _auth
from .routes import register_blueprints, start_lyrics_startup_scan

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    static_folder=os.path.join(PROJECT_ROOT, "static"),
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))
APP_VERSION = "1.8.0"

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


@app.get("/api/admin/audit-log")
@_auth.admin_required
def api_audit_log():
    return jsonify(db.get_audit_log(_int_arg("limit", 100, 1, 500)))


def _mask_ip_address(value: str) -> str:
    """Return a display-only IP address that never exposes the full address."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "xxx.xxx.xxx.xxx"
    if address.version == 4:
        parts = str(address).split(".")
        return f"{parts[0]}.xxx.xxx.{parts[3]}"
    parts = address.exploded.split(":")
    return f"{parts[0]}:xxxx:xxxx:xxxx:xxxx:xxxx:xxxx:{parts[-1]}"


def _monitor_connections():
    now = _time.time()
    with db.db() as conn:
        current = conn.execute(
            """SELECT c.username, c.product, c.ip_address, c.connected_at,
                      c.last_seen_at
               FROM connection_log c
               WHERE c.last_seen_at>?
                 AND (c.client_key IS NOT NULL OR EXISTS(
                     SELECT 1 FROM sessions s
                     WHERE s.connection_id=c.id AND s.expires_at>?
                 ))
               ORDER BY c.last_seen_at DESC""",
            (now - 120, now),
        ).fetchall()
        recent = conn.execute(
            """SELECT username, product, ip_address, connected_at, last_seen_at
               FROM connection_log ORDER BY connected_at DESC LIMIT 10"""
        ).fetchall()

    def serialize(row):
        item = dict(row)
        item["ip_address"] = _mask_ip_address(item["ip_address"])
        return item

    return [serialize(row) for row in current], [serialize(row) for row in recent]


def _record_client_heartbeat(product: str, client_key: str) -> None:
    now = _time.time()
    ip = _auth._get_client_ip()
    token = request.cookies.get(_auth.SESSION_COOKIE)
    username = g.user["username"] if g.user else "Gast"
    user_id = g.user["id"] if g.user else None
    with db.db() as conn:
        client_row = conn.execute(
            "SELECT id FROM connection_log WHERE client_key=?", (client_key,)
        ).fetchone()
        session_row = conn.execute(
            "SELECT connection_id FROM sessions WHERE token=?", (token,)
        ).fetchone() if token and g.user else None
        session_connection_id = (
            int(session_row["connection_id"])
            if session_row and session_row["connection_id"] is not None else None
        )

        if client_row:
            connection_id = int(client_row["id"])
            if session_connection_id and session_connection_id != connection_id:
                conn.execute(
                    "UPDATE sessions SET connection_id=? WHERE token=?",
                    (connection_id, token),
                )
                conn.execute(
                    "DELETE FROM connection_log WHERE id=?", (session_connection_id,)
                )
        elif session_connection_id:
            connection_id = session_connection_id
        else:
            cur = conn.execute("""
                INSERT INTO connection_log
                    (user_id, username, product, ip_address, connected_at,
                     last_seen_at, client_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, product, ip, now, now, client_key))
            connection_id = int(cur.lastrowid)

        conn.execute("""
            UPDATE connection_log
            SET user_id=?, username=?, product=?, ip_address=?,
                last_seen_at=?, client_key=?
            WHERE id=?
        """, (user_id, username, product, ip, now, client_key, connection_id))
        if token and g.user:
            conn.execute(
                "UPDATE sessions SET connection_id=? WHERE token=?",
                (connection_id, token),
            )


@app.post("/api/client/heartbeat")
def api_client_heartbeat():
    data = request.get_json(silent=True) or {}
    product = str(data.get("product") or "").strip().lower()
    client_key = str(data.get("client_id") or "").strip()
    if product not in ("adolar_web", "companion", "android"):
        return jsonify({"error": "invalid product"}), 400
    if not 8 <= len(client_key) <= 100 or not all(
        char.isalnum() or char in "-_" for char in client_key
    ):
        return jsonify({"error": "invalid client_id"}), 400
    _record_client_heartbeat(product, client_key)
    return jsonify({"ok": True})


def _iso_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    import datetime
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _backup_task_view() -> tuple[dict | None, list[dict]]:
    """Merge backup_service's own status/history into the shape tasks.py
    uses, so the monitor can show scan/BPM/thumbnail/optimize/backup jobs in
    one list. Backups keep their own file-based tracking (see backup_service.py
    and _run_backup_job) rather than going through tasks.py, since that also
    has to work for a separate scheduler process/thread."""
    try:
        root = _backup_root()
        status = backup_service.read_status(root)
        backups = backup_service.list_backups(root)
    except OSError:
        return None, []

    current = None
    if status.get("state") == "running" and backup_service.is_backup_running(root):
        current = {
            "task_type": "backup",
            "trigger": status.get("source", "manual"),
            "started_at": _iso_to_epoch(status.get("started_at")),
            "current": None,
            "total": None,
            "detail": None,
        }

    recent = [
        {
            "task_type": "backup",
            "trigger": b.get("source", "manual"),
            "status": "completed",
            "started_at": _iso_to_epoch(b.get("created_at")),
            "finished_at": _iso_to_epoch(b.get("created_at")),
            "detail": None,
        }
        for b in backups
    ]
    # Surface a failed/interrupted attempt too, if it's newer than the last
    # successful backup (otherwise a stale failure would linger forever).
    if status.get("state") in ("failed",) or (
        status.get("state") == "running" and not backup_service.is_backup_running(root)
    ):
        failed_at = _iso_to_epoch(status.get("failed_at") or status.get("started_at"))
        newest_ok = recent[0]["finished_at"] if recent else None
        if failed_at and (not newest_ok or failed_at > newest_ok):
            recent.insert(0, {
                "task_type": "backup",
                "trigger": status.get("source", "manual"),
                "status": "failed",
                "started_at": _iso_to_epoch(status.get("started_at")),
                "finished_at": failed_at,
                "detail": status.get("error"),
            })

    return current, recent


@app.get("/api/admin/monitor")
@_auth.admin_required
def api_admin_monitor():
    memory = psutil.virtual_memory()
    current, recent = _monitor_connections()

    backup_current, backup_recent = _backup_task_view()
    current_tasks = tasks.running() + ([backup_current] if backup_current else [])
    recent_tasks = sorted(
        tasks.recent(10) + backup_recent,
        key=lambda t: t.get("finished_at") or 0, reverse=True,
    )[:10]

    return jsonify({
        "system": {
            "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            "cpu_count": psutil.cpu_count() or 1,
            "memory_percent": round(memory.percent, 1),
            "memory_used": memory.used,
            "memory_total": memory.total,
            "boot_time": psutil.boot_time(),
        },
        "current_connections": current,
        "recent_connections": recent,
        "current_tasks": current_tasks,
        "recent_tasks": recent_tasks,
        "active_window_seconds": 120,
        "sampled_at": _time.time(),
    })


# ── Database backups (admin only) ────────────────────────────────────────────

def _run_backup_job(source: str, actor_id: int | None = None):
    try:
        result = backup_service.create_backup(
            db.current_db_path(),
            _backup_root(),
            control_db_path=db.CONTROL_DB_PATH,
            jingle_root=JINGLE_ROOT,
            app_version=APP_VERSION,
            source=source,
            retention=_backup_retention(),
        )
        db.log_audit(
            actor_id, "backup.created", result["backup_id"],
            json.dumps({"source": source, "size": result["database"]["size"]}),
        )
    except backup_service.BackupInProgress:
        return
    except Exception:
        logging.getLogger(__name__).exception("Database backup failed")


def _start_backup_job(source: str, actor_id: int | None = None) -> bool:
    if backup_service.is_backup_running(_backup_root()):
        return False
    _start_library_thread(
        _run_backup_job,
        args=(source, actor_id),
        name=f"adolar-backup-{source}",
    )
    return True


@app.get("/api/admin/backups")
@_auth.admin_required
def api_backups_list():
    try:
        backups = backup_service.list_backups(_backup_root())
        status = backup_service.read_status(_backup_root())
        if status.get("state") == "running" and not backup_service.is_backup_running(_backup_root()):
            status = {
                "state": "failed",
                "error": "Die letzte Sicherung wurde unterbrochen. Sie kann erneut gestartet werden.",
            }
    except OSError as exc:
        logging.getLogger(__name__).warning("Backup-Ziel nicht verfügbar (%s)", exc)
        return jsonify({
            "error": "Backup-Ziel nicht verfügbar.",
            "configured_path": _backup_root(),
        }), 503
    return jsonify({
        "backups": backups,
        "status": status,
        "configured_path": _backup_root(),
        "automatic": _backup_auto_enabled(),
        "hour": _backup_hour(),
        "retention": _backup_retention(),
    })


@app.put("/api/admin/backups/config")
@_auth.admin_required
def api_backups_config_update():
    data = request.get_json(silent=True) or {}
    try:
        if "enabled" not in data or "hour" not in data or "retention" not in data:
            raise errors.ValidationError("Bitte enabled, hour und retention angeben.")
        enabled = bool(data["enabled"])
        hour = int(data["hour"])
        retention = int(data["retention"])
        if not 0 <= hour <= 23:
            raise errors.ValidationError("Die Startstunde muss zwischen 0 und 23 liegen.")
        if not 1 <= retention <= 365:
            raise errors.ValidationError("Die Anzahl behaltener Sicherungen muss zwischen 1 und 365 liegen.")
        path = data.get("path")
        if path is not None:
            path = str(path).strip()
            if not path:
                raise errors.ValidationError("Bitte einen Backup-Pfad angeben.")
    except (TypeError, ValueError) as exc:
        return _client_error("Ungültige Sicherungs-Konfiguration.", exc)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    if path is not None:
        try:
            backup_service.ensure_backup_root(path)
        except OSError as exc:
            return _client_error("Backup-Pfad ist nicht beschreibbar.", exc, 503)
        db.set_setting("backup_root", path)
    db.set_setting("backup_auto_enabled", "1" if enabled else "0")
    db.set_setting("backup_hour", str(hour))
    db.set_setting("backup_retention", str(retention))
    db.log_audit(
        g.user["id"], "backup.config_updated", None,
        json.dumps({"enabled": enabled, "hour": hour, "retention": retention, "path": path}),
    )
    return jsonify({
        "automatic": enabled, "hour": hour, "retention": retention, "configured_path": _backup_root(),
    })


@app.post("/api/admin/backups")
@_auth.admin_required
def api_backups_create():
    try:
        backup_service.ensure_backup_root(_backup_root())
    except OSError as exc:
        return _client_error("Backup-Ziel nicht beschreibbar.", exc, 503)
    if not _start_backup_job("manual", g.user["id"]):
        return jsonify({"error": "Eine Datensicherung läuft bereits."}), 409
    return jsonify({"status": "started"}), 202


@app.get("/api/admin/backups/<backup_id>/<kind>")
@_auth.admin_required
def api_backups_download(backup_id, kind):
    try:
        path = backup_service.get_backup_file(_backup_root(), backup_id, kind)
    except FileNotFoundError:
        abort(404)
    suffixes = {
        "database": ".db", "control": "-control.db", "jingles": "-radio-jingles.tar.gz",
        "manifest": "-manifest.json",
    }
    if kind not in suffixes:
        abort(404)
    return send_file(
        path, as_attachment=True,
        download_name=f"{backup_id}{suffixes[kind]}", conditional=True,
    )


@app.delete("/api/admin/backups/<backup_id>")
@_auth.admin_required
def api_backups_delete(backup_id):
    try:
        backup_service.delete_backup(_backup_root(), backup_id)
    except FileNotFoundError:
        abort(404)
    db.log_audit(g.user["id"], "backup.deleted", backup_id)
    return jsonify({"ok": True})


# ── Library management (admin only) ────────────────────────────────────────────

@app.get("/api/admin/libraries")
@_auth.admin_required
def api_libraries_list():
    libs, active_id = libraries.list_libraries(
        LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH,
    )
    return jsonify({"libraries": libs, "active_id": active_id})


@app.post("/api/admin/libraries")
@_auth.admin_required
def api_libraries_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    music_path_input = (data.get("music_path") or "").strip()
    # Admin-supplied library root, deliberately unrestricted (this endpoint's
    # whole purpose is letting an admin point at any host directory) —
    # resolved to a canonical absolute path before any filesystem check.
    music_path = os.path.realpath(music_path_input) if music_path_input else ""
    try:
        if not name:
            raise errors.ValidationError("Bitte einen Namen für die Bibliothek angeben.")
        if not music_path or not os.path.isdir(music_path):
            raise errors.ValidationError("Der angegebene Pfad existiert nicht oder ist kein Verzeichnis.")
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    lib = libraries.add_library(
        LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH,
        LIBRARIES_DIR, name, music_path,
    )
    with library_context.bind(lib["db_path"], lib["music_path"]):
        db.init_db()
        db.log_audit(g.user["id"], "library.created", lib["id"], json.dumps(lib))
    return jsonify(lib), 201


@app.post("/api/admin/libraries/<library_id>/activate")
@_auth.admin_required
def api_libraries_activate(library_id):
    try:
        lib = libraries.set_active(LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH, library_id)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc, 404)
    with library_context.bind(lib["db_path"], lib["music_path"]):
        db.init_db()
        db.log_audit(g.user["id"], "library.activated", lib["id"])
    return jsonify(lib)


@app.put("/api/admin/libraries/<library_id>/move")
@_auth.admin_required
def api_libraries_move(library_id):
    _libs, active_id = libraries.list_libraries(LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH)
    data = request.get_json(silent=True) or {}
    new_music_path_input = (data.get("new_music_path") or "").strip()
    # Admin-supplied library root, deliberately unrestricted — see the same
    # comment in api_libraries_create.
    new_music_path = os.path.realpath(new_music_path_input) if new_music_path_input else ""
    try:
        if library_id != active_id:
            raise errors.ValidationError("Bitte zuerst diese Bibliothek aktivieren, bevor sie umgezogen wird.")
        if not new_music_path or not os.path.isdir(new_music_path):
            raise errors.ValidationError("Der neue Pfad existiert nicht oder ist kein Verzeichnis.")
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    old_music_path = _current_music_root()
    updated = db.migrate_track_paths(old_music_path, new_music_path)
    lib = libraries.update_music_path(
        LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH, library_id, new_music_path,
    )
    db.log_audit(
        g.user["id"], "library.moved", library_id,
        json.dumps({"old_path": old_music_path, "new_path": new_music_path, "tracks_updated": updated}),
    )
    return jsonify({"library": lib, "tracks_updated": updated})


@app.post("/api/admin/libraries/<library_id>/rename-path")
@_auth.admin_required
def api_libraries_rename_path(library_id):
    """Rewrite tracks.path for a subfolder rename/move within the active
    library. Unlike /move above, this does NOT touch the library's
    registered music_path — only the DB rows under old_path are rewritten.
    Intended for external tools (e.g. Adolar Taggster) that rename/move a
    folder on disk themselves and just need Adolar's DB kept in sync."""
    _libs, active_id = libraries.list_libraries(LIBRARY_REGISTRY_PATH, MUSIC_ROOT, db.DB_PATH)
    data = request.get_json(silent=True) or {}
    old_path_input = (data.get("old_path") or "").strip()
    new_path_input = (data.get("new_path") or "").strip()
    old_path = os.path.realpath(old_path_input) if old_path_input else ""
    new_path = os.path.realpath(new_path_input) if new_path_input else ""
    music_root = _current_music_root()
    try:
        if library_id != active_id:
            raise errors.ValidationError("Bitte zuerst diese Bibliothek aktivieren.")
        if not old_path_input or not new_path_input:
            raise errors.ValidationError("old_path und new_path werden benötigt.")
        if old_path != music_root and not old_path.startswith(music_root + os.sep):
            raise errors.ValidationError("old_path liegt nicht innerhalb der aktiven Bibliothek.")
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    try:
        updated = db.migrate_track_paths(old_path, new_path)
    except sqlite3.IntegrityError as exc:
        return _client_error("Zielpfad kollidiert mit vorhandenen Tracks.", exc, 409)
    db.log_audit(
        g.user["id"], "library.path_renamed", library_id,
        json.dumps({"old_path": old_path, "new_path": new_path, "tracks_updated": updated}),
    )
    return jsonify({"tracks_updated": updated})


@app.post("/api/admin/library/covers")
@_auth.admin_required
def api_library_covers():
    """Generate thumbnails for cover art already found on disk/in tags.

    This does not re-read tags from files that a normal scan considers
    unchanged; use "Bibliothek neu scannen" for that.
    """
    scanner.run_thumb_generation()
    return jsonify({"status": "started"})


@app.post("/api/admin/database/optimize")
@_auth.admin_required
def api_database_optimize():
    """Integrity-check, VACUUM, and refresh planner stats for both databases.

    Runs synchronously (VACUUM on a typical library database takes seconds,
    not minutes) so the response reflects the actual result.
    """
    task_id = tasks.start("db_optimize", "manual")
    try:
        result = db.optimize_database()
    except sqlite3.OperationalError as exc:
        tasks.finish(task_id, status="failed", detail=str(exc))
        return _client_error("Datenbank-Optimierung fehlgeschlagen.", exc, 503)
    tasks.finish(task_id, status="completed")
    db.log_audit(g.user["id"], "database.optimized", None, json.dumps(result))
    return jsonify(result)


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["HEAD"])
def index_head():
    return "", 200

@app.get("/")
def index():
    if _auth.user_count() == 0:
        return redirect("/setup")
    return render_template("index.html", app_version=APP_VERSION)


@app.get("/miniplayer")
def miniplayer():
    return render_template("miniplayer.html")


@app.get("/hilfe/manual.html")
def manual():
    return send_file(os.path.join(PROJECT_ROOT, "hilfe", "manual.html"))


@app.get("/radio")
def radio_companion():
    access = db.get_setting("companion_access", "public")
    if access == "disabled":
        abort(404)
    if access == "authenticated" and not g.user:
        return redirect("/login?next=/radio")
    return render_template("radio.html")


@app.get("/radio/settings")
def radio_companion_settings():
    if not g.user or g.user.get("role") != "admin":
        abort(403)
    return render_template("radio_settings.html", app_version=APP_VERSION)


# ── Tracks ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
def api_search():
    q           = request.args.get("q", "").strip()
    genre       = request.args.get("genre", "").strip() or None
    decade      = request.args.get("decade", "").strip() or None
    fmt         = request.args.get("format", "").strip() or None
    min_dur     = request.args.get("min_dur") or None
    max_dur     = request.args.get("max_dur") or None
    min_bitrate = request.args.get("min_bitrate") or None
    year_min    = request.args.get("year_min") or None
    year_max    = request.args.get("year_max") or None
    bpm_min     = request.args.get("bpm_min") or None
    bpm_max     = request.args.get("bpm_max") or None
    artist_q    = request.args.get("artist", "").strip()
    title_q     = request.args.get("title", "").strip()
    album_q     = request.args.get("album", "").strip()
    album_eq    = request.args.get("album_eq", "").strip() or None
    dir_eq      = request.args.get("dir_eq")  # exact folder match; "" is a valid value, so no strip/or-None
    loved       = request.args.get("loved") == "1"
    page     = _int_arg("page",     1,   min_val=1)
    per_page = _int_arg("per_page", 50,  min_val=1, max_val=200)
    sort     = request.args.get("sort", "artist")
    do_count = request.args.get("count", "1") != "0"

    try:
        if min_dur:     min_dur     = int(min_dur)
        if max_dur:     max_dur     = int(max_dur)
        if min_bitrate: min_bitrate = int(min_bitrate)
        if year_min:    year_min    = int(year_min)
        if year_max:    year_max    = int(year_max)
        if bpm_min:     bpm_min     = float(bpm_min)
        if bpm_max:     bpm_max     = float(bpm_max)
    except ValueError:
        return jsonify({"error": "invalid numeric parameter"}), 400

    user_id = g.user["id"] if g.user else None
    total, tracks = db.search_tracks(
        query=q, artist_query=artist_q, title_query=title_q, album_query=album_q,
        album_eq=album_eq, dir_eq=dir_eq,
        genre=genre, decade=decade, fmt=fmt,
        min_dur=min_dur, max_dur=max_dur, min_bitrate=min_bitrate,
        year_min=year_min, year_max=year_max,
        bpm_min=bpm_min, bpm_max=bpm_max,
        page=page, per_page=per_page, sort=sort, count=do_count,
        loved_only=loved, include_loved=bool(user_id and db.get_lastfm_account(user_id)),
        user_id=user_id,
    )
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "results": tracks,
    })


@app.get("/api/albums")
def api_albums():
    """Distinct albums matching the same filter set as /api/search, for the
    album-first browsing view (album search shows albums, not every track)."""
    q           = request.args.get("q", "").strip()
    genre       = request.args.get("genre", "").strip() or None
    decade      = request.args.get("decade", "").strip() or None
    fmt         = request.args.get("format", "").strip() or None
    min_dur     = request.args.get("min_dur") or None
    max_dur     = request.args.get("max_dur") or None
    min_bitrate = request.args.get("min_bitrate") or None
    year_min    = request.args.get("year_min") or None
    year_max    = request.args.get("year_max") or None
    bpm_min     = request.args.get("bpm_min") or None
    bpm_max     = request.args.get("bpm_max") or None
    artist_q    = request.args.get("artist", "").strip()
    title_q     = request.args.get("title", "").strip()
    album_q     = request.args.get("album", "").strip()
    page     = _int_arg("page",     1,   min_val=1)
    per_page = _int_arg("per_page", 50,  min_val=1, max_val=200)
    sort     = request.args.get("sort", "album")
    do_count = request.args.get("count", "1") != "0"

    try:
        if min_dur:     min_dur     = int(min_dur)
        if max_dur:     max_dur     = int(max_dur)
        if min_bitrate: min_bitrate = int(min_bitrate)
        if year_min:    year_min    = int(year_min)
        if year_max:    year_max    = int(year_max)
        if bpm_min:     bpm_min     = float(bpm_min)
        if bpm_max:     bpm_max     = float(bpm_max)
    except ValueError:
        return jsonify({"error": "invalid numeric parameter"}), 400

    total, albums = db.search_albums(
        query=q, artist_query=artist_q, title_query=title_q, album_query=album_q,
        genre=genre, decade=decade, fmt=fmt,
        min_dur=min_dur, max_dur=max_dur, min_bitrate=min_bitrate,
        year_min=year_min, year_max=year_max,
        bpm_min=bpm_min, bpm_max=bpm_max,
        page=page, per_page=per_page, sort=sort, count=do_count,
    )
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "results": albums,
    })


@app.get("/health")
def health():
    """Unauthenticated liveness probe for Docker/orchestration healthchecks."""
    return jsonify({"status": "ok"})


# ── Genres / Stats ────────────────────────────────────────────────────────────

@app.get("/api/genres")
def api_genres():
    return jsonify(db.get_genres())


@app.get("/api/stats")
def api_stats():
    stats = db.get_stats()
    sc = scanner.status()
    persisted_scan = db.get_scanner_status()
    stats["version"] = APP_VERSION
    stats["last_scan"] = sc.get("finished_at") or persisted_scan.get("finished_at")
    stats["disco_active"] = _disco_active()
    return jsonify(stats)


@app.get("/api/disco-status")
def api_disco_status():
    """Lightweight endpoint polled by the UI to show Disco connection badge."""
    _touch_disco()  # also counts as a keepalive if Disco calls this
    return jsonify({
        "active": _disco_active(),
        "last_seen": _disco_last_seen or None,
    })


# ── Cover art ─────────────────────────────────────────────────────────────────

# Store thumbnails next to the DB so they survive container restarts
_db_dir = os.path.dirname(os.environ.get("DB_PATH", "") or os.path.expanduser("~/.cache/adolar.db"))
_THUMB_DIR = os.path.join(_db_dir, "thumbs")
_THUMB_SIZE = (80, 80)

def _thumb_path(hash_: str) -> str:
    return os.path.join(_THUMB_DIR, f"{hash_}.webp")

def _make_thumb(data: bytes) -> bytes | None:
    try:
        import io as _io

        from PIL import Image
        img = Image.open(_io.BytesIO(data))
        img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="WEBP", quality=75, method=4)
        return buf.getvalue()
    except Exception:
        return None


@app.get("/api/cover/<hash_>")
def api_cover(hash_):
    import io
    full = request.args.get("full") == "1"

    # Full size requested (e.g. radio companion) — skip thumbnail
    if not full:
        tp = _thumb_path(hash_)
        if os.path.exists(tp):
            resp = send_file(tp, mimetype="image/webp", max_age=86400 * 365)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            resp.headers["ETag"] = f'"{hash_}-thumb"'
            return resp

    data, mime = db.get_cover(hash_)
    if data is None:
        abort(404)

    if not full:
        thumb = _make_thumb(data)
        if thumb:
            os.makedirs(_THUMB_DIR, exist_ok=True)
            with open(_thumb_path(hash_), "wb") as f:
                f.write(thumb)
            resp = send_file(io.BytesIO(thumb), mimetype="image/webp", max_age=86400 * 365)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            resp.headers["ETag"] = f'"{hash_}-thumb"'
            return resp

    resp = send_file(io.BytesIO(data), mimetype=mime, max_age=86400 * 365)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["ETag"] = f'"{hash_}"'
    return resp


# ── Audio streaming ───────────────────────────────────────────────────────────

_stream_response_lock = threading.Lock()
_active_stream_responses = 0


def _begin_stream_response(track_id: int, status: int, range_header: str | None) -> tuple[float, int]:
    global _active_stream_responses
    with _stream_response_lock:
        _active_stream_responses += 1
        active = _active_stream_responses
    started = _time.perf_counter()
    logging.getLogger(__name__).info(
        "audio stream start track=%s status=%s range=%s active=%s",
        track_id, status, range_header or "full", active,
    )
    return started, active


def _end_stream_response(track_id: int, started: float) -> None:
    global _active_stream_responses
    with _stream_response_lock:
        _active_stream_responses = max(0, _active_stream_responses - 1)
        active = _active_stream_responses
    logging.getLogger(__name__).info(
        "audio stream end track=%s duration_ms=%.1f active=%s",
        track_id, (_time.perf_counter() - started) * 1000, active,
    )


def _set_stream_cache_headers(response, *, etag: str, last_modified: str, immutable: bool):
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Last-Modified"] = last_modified
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Cache-Control"] = (
        "private, max-age=31536000, immutable" if immutable else "private, no-cache"
    )
    return response

@app.get("/api/stream/<int:track_id>")
def api_stream(track_id):
    _touch_disco()
    with db.db() as conn:
        row = conn.execute(
            "SELECT path FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    if row is None:
        abort(404)

    path = _safe_path(row["path"])
    if path is None or not os.path.isfile(path):
        abort(404)

    stat = os.stat(path)
    size = stat.st_size
    # SQLite stores scanner mtimes as REAL; microseconds preserve the available
    # precision while producing exactly the same key from the live stat result.
    version = f"{int(stat.st_mtime * 1_000_000)}-{size}"
    etag = f"track-{track_id}-{version}"
    last_modified = http_date(stat.st_mtime)
    immutable = request.args.get("v") == version
    not_modified = request.if_none_match and request.if_none_match.contains(etag)
    if not not_modified and not request.if_none_match and request.if_modified_since:
        not_modified = stat.st_mtime <= request.if_modified_since.timestamp() + 1
    if not_modified:
        response = make_response("", 304)
        return _set_stream_cache_headers(
            response, etag=etag, last_modified=last_modified, immutable=immutable,
        )

    range_header = request.headers.get("Range")
    if_range = request.headers.get("If-Range")
    if if_range and if_range not in {f'"{etag}"', last_modified}:
        range_header = None
    mime = _guess_mime(path)

    if range_header:
        byte1, byte2 = _parse_range(range_header, size)
        if byte1 is None:
            response = make_response("", 416)
            response.headers["Content-Range"] = f"bytes */{size}"
            return _set_stream_cache_headers(
                response, etag=etag, last_modified=last_modified, immutable=immutable,
            )
        length = byte2 - byte1 + 1
        started, _active = _begin_stream_response(track_id, 206, range_header)

        def generate():
            first_chunk = True
            try:
                with open(path, "rb") as f:
                    f.seek(byte1)
                    remaining = length
                    while remaining:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        if first_chunk:
                            first_chunk = False
                            logging.getLogger(__name__).info(
                                "audio stream first-byte track=%s ttfb_ms=%.1f",
                                track_id, (_time.perf_counter() - started) * 1000,
                            )
                        remaining -= len(chunk)
                        yield chunk
            finally:
                _end_stream_response(track_id, started)

        from flask import Response
        headers = {
            "Content-Range": f"bytes {byte1}-{byte2}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": length,
            "Content-Type": mime,
        }
        response = Response(generate(), 206, headers=headers)
        return _set_stream_cache_headers(
            response, etag=etag, last_modified=last_modified, immutable=immutable,
        )

    started, _active = _begin_stream_response(track_id, 200, None)
    response = send_file(path, mimetype=mime, conditional=False)
    response.call_on_close(lambda: _end_stream_response(track_id, started))
    return _set_stream_cache_headers(
        response, etag=etag, last_modified=last_modified, immutable=immutable,
    )


def _guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".m4a": "audio/mp4",  ".ogg": "audio/ogg",
        ".opus": "audio/ogg", ".aac": "audio/aac",
        ".wav": "audio/wav",
    }.get(ext, "application/octet-stream")


def _parse_range(header: str, size: int):
    """Returns (byte1, byte2) or (None, None) on invalid range."""
    try:
        ranges = header.replace("bytes=", "").split("-")
        byte1 = int(ranges[0]) if ranges[0] else 0
        byte2 = int(ranges[1]) if ranges[1] else size - 1
        byte2 = min(byte2, size - 1)
        if byte1 < 0 or byte1 > byte2 or byte1 >= size:
            return None, None
        return byte1, byte2
    except (ValueError, IndexError):
        return None, None


# ── Download / ZIP ────────────────────────────────────────────────────────────

@app.post("/api/download")
def api_download():
    if not _auth.can(g.user, "download_tracks"):
        return jsonify({"error": "Download nicht erlaubt."}), 403
    import io
    import time
    import zipfile
    ids = request.json.get("ids", [])
    if not ids:
        return jsonify({"error": "no ids"}), 400
    if len(ids) > MAX_DOWNLOAD_IDS:
        return jsonify({"error": f"too many ids (max {MAX_DOWNLOAD_IDS})"}), 400

    # Ensure all IDs are integers to prevent injection
    try:
        ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return jsonify({"error": "invalid ids"}), 400

    with db.db() as conn:
        rows = conn.execute(
            f"SELECT id, path, title, artist FROM tracks WHERE id IN ({','.join('?'*len(ids))})",
            ids
        ).fetchall()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for row in rows:
            path = _safe_path(row["path"])
            if path is None or not os.path.isfile(path):
                continue
            artist  = (row["artist"] or "Unbekannt").replace("/", "-")
            title   = (row["title"]  or os.path.basename(path)).replace("/", "-")
            ext     = os.path.splitext(path)[1]
            arcname = f"{artist} - {title}{ext}"
            zf.write(path, arcname)

    buf.seek(0)
    filename = f"adolar_{int(time.time())}.zip"
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=filename)


# ── Play count ───────────────────────────────────────────────────────────────

@app.post("/api/track/<int:track_id>/bpm")
@_auth.admin_required
def api_track_bpm(track_id):
    """Accept a BPM value from an external tool (e.g. Adolar Disco)."""
    data = request.get_json(silent=True) or {}
    bpm = data.get("bpm")
    if bpm is None or not isinstance(bpm, (int, float)) or bpm <= 0:
        return jsonify({"error": "bpm must be a positive number"}), 400
    updated = db.update_bpm(track_id, round(float(bpm), 2))
    return jsonify({"ok": True, "updated": updated})


@app.post("/api/track/<int:track_id>/played")
def api_track_played(track_id):
    user = g.get("user")
    if not user:
        abort(401)

    source = str((request.get_json(silent=True) or {}).get("source") or "unknown")
    source = source.strip().lower()
    contributes = bool(user.get("contributes_playcount"))
    record_personal = source != "radio"
    new_count, _ = db.record_user_play(
        user["id"], track_id, contributes, record_personal=record_personal,
    )
    if new_count is None:
        abort(404)

    return jsonify({
        "ok": True,
        "play_count": new_count if contributes else None,
        "contributed": contributes,
        "personalized": record_personal,
    })


@app.post("/api/track/<int:track_id>/disco-played")
def api_track_disco_played(track_id):
    """Called by Adolar Disco — records play in disco counter (user_id=0), never writes file."""
    with db.db() as conn:
        if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone():
            abort(404)
    db.increment_user_play_count(0, track_id)
    return jsonify({"ok": True})


def _read_play_count_tag(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            tags = ID3(path)
            pcnt = tags.get("PCNT")
            return int(pcnt.count) if pcnt else 0
        elif ext == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(path)
            raw = tags.get("play_count")
            return int(raw[0]) if raw else 0
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            tags = MP4(path)
            raw = tags.get("----:com.apple.iTunes:play_count")
            return int(raw[0]) if raw else 0
    except Exception:
        pass
    return 0


def _write_play_count_tag(path: str, count: int):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, PCNT
            try:
                tags = ID3(path)
            except Exception:
                tags = ID3()
            tags["PCNT"] = PCNT(count=count)
            tags.save(path)
        elif ext == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(path)
            tags["play_count"] = [str(count)]
            tags.save()
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            tags = MP4(path)
            tags["----:com.apple.iTunes:play_count"] = [str(count).encode()]
            tags.save()
        # ogg/opus/wav: skip — no standard play count field
        else:
            return False
        return True
    except Exception as e:
        logging.getLogger(__name__).warning("Could not write play count tag to %s: %s", path, e)
        return False


_play_count_tag_sync = {
    "running": False, "written": 0, "failed": 0, "error": None, "finished_at": None
}


def _flush_play_count_tags():
    if _play_count_tag_sync["running"]:
        return
    _play_count_tag_sync.update(running=True, written=0, failed=0, error=None)
    try:
        while True:
            rows = db.get_dirty_play_count_tags(limit=500)
            if not rows:
                break
            progressed = False
            for row in rows:
                path = _safe_path(row["path"])
                if not path or not os.path.isfile(path):
                    _play_count_tag_sync["failed"] += 1
                    continue
                count = max(int(row["play_count"]), _read_play_count_tag(path))
                if _write_play_count_tag(path, count):
                    db.merge_archive_play_count(row["id"], count)
                    db.mark_play_count_tag_written(row["id"], count)
                    _play_count_tag_sync["written"] += 1
                    progressed = True
                else:
                    _play_count_tag_sync["failed"] += 1
            if len(rows) < 500 or not progressed:
                break
    except Exception as exc:
        logging.getLogger(__name__).exception("Play count tag sync failed")
        _play_count_tag_sync["error"] = str(exc)
    finally:
        _play_count_tag_sync.update(running=False, finished_at=_time.time())


@app.get("/api/playcount-tags/status")
@_auth.admin_required
def api_play_count_tags_status():
    return jsonify({**db.get_play_count_tag_status(), **_play_count_tag_sync})


@app.post("/api/playcount-tags/sync")
@_auth.admin_required
def api_play_count_tags_sync():
    if _play_count_tag_sync["running"]:
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_flush_play_count_tags)
    return jsonify({"ok": True})


# ── Radio / Random ────────────────────────────────────────────────────────────

@app.get("/api/random")
def api_random():
    _touch_disco()
    count   = min(int(request.args.get("count", 25)), 100)
    exclude = [int(x) for x in request.args.getlist("exclude") if x.isdigit()]
    token, shuffle_state = smart_shuffle.get_session(
        request.args.get("shuffle_session"), "random"
    )
    with shuffle_state.lock:
        tracks = db.get_random_tracks(count, exclude, shuffle_state=shuffle_state)
    response = jsonify(tracks)
    response.headers["X-Shuffle-Session"] = token
    return response


@app.get("/api/shuffle")
def api_shuffle():
    """Smart-shuffle the complete current search, filter, or static playlist."""
    count = _int_arg("count", 25, min_val=1, max_val=100)
    playlist_id = request.args.get("playlist_id")
    user_id = g.user["id"] if g.user else 0

    raw = {
        "q": request.args.get("q", "").strip(),
        "artist": request.args.get("artist", "").strip(),
        "title": request.args.get("title", "").strip(),
        "album": request.args.get("album", "").strip(),
        "genre": request.args.get("genre", "").strip(),
        "decade": request.args.get("decade", "").strip(),
        "format": request.args.get("format", "").strip(),
        "min_dur": request.args.get("min_dur", "").strip(),
        "max_dur": request.args.get("max_dur", "").strip(),
        "min_bitrate": request.args.get("min_bitrate", "").strip(),
        "year_min": request.args.get("year_min", "").strip(),
        "year_max": request.args.get("year_max", "").strip(),
        "bpm_min": request.args.get("bpm_min", "").strip(),
        "bpm_max": request.args.get("bpm_max", "").strip(),
        "loved": request.args.get("loved") == "1",
        "sort": request.args.get("sort", "artist"),
    }
    numeric = ("min_dur", "max_dur", "min_bitrate", "year_min", "year_max")
    decimal = ("bpm_min", "bpm_max")
    try:
        parsed = {
            key: (int(raw[key]) if raw[key] else None)
            for key in numeric
        }
        parsed.update({
            key: (float(raw[key]) if raw[key] else None)
            for key in decimal
        })
    except ValueError:
        return jsonify({"error": "invalid numeric parameter"}), 400

    context_data = {**raw, "playlist_id": playlist_id or None, "user_id": user_id}
    context_hash = hashlib.sha256(
        json.dumps(context_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    token, shuffle_state = smart_shuffle.get_session(
        request.args.get("shuffle_session"), f"search:{context_hash}"
    )

    with shuffle_state.lock:
        if playlist_id:
            try:
                playlist_id = int(playlist_id)
            except ValueError:
                return jsonify({"error": "invalid playlist_id"}), 400
            candidates = db.get_playlist_tracks(playlist_id, user_id)
            if candidates is None:
                abort(404)
            total = len(candidates)
        else:
            need_stats = shuffle_state.total_tracks is None
            total, candidates = db.search_tracks(
                query=raw["q"], artist_query=raw["artist"],
                title_query=raw["title"], album_query=raw["album"],
                genre=raw["genre"] or None, decade=raw["decade"] or None,
                fmt=raw["format"] or None,
                min_dur=parsed["min_dur"], max_dur=parsed["max_dur"],
                min_bitrate=parsed["min_bitrate"],
                year_min=parsed["year_min"], year_max=parsed["year_max"],
                bpm_min=parsed["bpm_min"], bpm_max=parsed["bpm_max"],
                page=1, per_page=2500, sort=raw["sort"], count=need_stats,
                loved_only=raw["loved"],
                include_loved=bool(user_id and db.get_lastfm_account(user_id)),
                user_id=user_id, random_order=True,
            )
            if not need_stats:
                total = shuffle_state.total_tracks or 0

        if shuffle_state.total_tracks is None:
            shuffle_state.total_tracks = total
            shuffle_state.unique_artists = len({
                (track.get("artist") or "").strip().casefold()
                for track in candidates if (track.get("artist") or "").strip()
            })
            shuffle_state.unique_albums = len({
                ((track.get("artist") or "").strip().casefold(),
                 (track.get("album") or "").strip().casefold())
                for track in candidates if (track.get("album") or "").strip()
            })
            shuffle_state.unique_genres = len({
                (track.get("genre") or "").strip().casefold()
                for track in candidates if (track.get("genre") or "").strip()
            })

        selected = smart_shuffle.select_tracks(
            candidates, count, shuffle_state,
            shuffle_state.total_tracks or 0,
            shuffle_state.unique_artists or 0,
            shuffle_state.unique_albums or 0,
            unique_genres=shuffle_state.unique_genres or 0,
            use_genre_spacing=not bool(raw["genre"]),
        )

    response = jsonify(selected)
    response.headers["X-Shuffle-Session"] = token
    response.headers["X-Shuffle-Total"] = str(shuffle_state.total_tracks or 0)
    return response


@app.get("/api/radio-stations")
def api_radio_stations_list():
    user = g.get("user")
    include_all_private = bool(
        user and user.get("role") == "admin" and request.args.get("admin") == "1"
    )
    user_id = user["id"] if user else None
    stations = db.list_radio_stations(
        user_id=user_id, include_all_private=include_all_private,
    )
    a4u_available = False
    if user:
        global_settings = adolar4u.get_global_settings()
        user_settings = adolar4u.get_user_settings(user["id"])
        a4u_available = global_settings["enabled"] and user_settings["enabled"]
    stations = [
        station for station in stations
        if station.get("engine") != "adolar4u" or a4u_available
    ]
    return jsonify(stations)


@app.post("/api/radio-stations")
def api_radio_stations_create():
    if not _auth.can(g.user, "create_radio_stations"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    requested_scope = data.get("scope") or "private"
    if g.user["role"] != "admin":
        requested_scope = "private"
    elif requested_scope not in ("global", "private"):
        requested_scope = "global"
    try:
        station_id = db.create_radio_station(
            name=name,
            description=data.get("description") or "",
            filter_def=data.get("filter") or {"mode": "all", "rules": []},
            user_id=g.user["id"],
            scope=requested_scope,
        )
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Senderdefinition.", e)
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "name already exists"}), 409
        raise
    return jsonify(db.get_radio_station(station_id)), 201


@app.put("/api/radio-stations/<int:station_id>")
def api_radio_stations_update(station_id):
    if not _auth.can(g.user, "create_radio_stations"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        ok = db.update_radio_station(
            station_id,
            name=name,
            description=data.get("description") or "",
            filter_def=data.get("filter") or {"mode": "all", "rules": []},
            user_id=g.user["id"],
            is_admin=g.user["role"] == "admin",
            scope=data.get("scope"),
        )
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Senderdefinition.", e)
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "name already exists"}), 409
        raise
    if not ok:
        return jsonify({"error": "not found or system station"}), 404
    return jsonify(db.get_radio_station(station_id))


@app.delete("/api/radio-stations/<int:station_id>")
def api_radio_stations_delete(station_id):
    if not _auth.can(g.user, "create_radio_stations"):
        return jsonify({"error": "forbidden"}), 403
    if not db.delete_radio_station(station_id, g.user["id"], g.user["role"] == "admin"):
        return jsonify({"error": "not found or system station"}), 404
    return jsonify({"ok": True})


@app.post("/api/radio-stations/test")
@_auth.admin_required
def api_radio_stations_test():
    data = request.get_json(silent=True) or {}
    count = max(1, min(int(data.get("count") or 50), 100))
    try:
        tracks = db.get_radio_filter_tracks(
            data.get("filter") or {"mode": "all", "rules": []},
            count=count,
            exclude_ids=[],
            user_id=g.user["id"],
        )
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Senderdefinition.", e)
    return jsonify({"results": tracks, "total": len(tracks)})


def _can_manage_station_or_404(station_id: int):
    if not _auth.can(g.user, "create_radio_stations"):
        return jsonify({"error": "forbidden"}), 403
    if not db.can_manage_radio_station(station_id, g.user["id"], g.user["role"] == "admin"):
        return jsonify({"error": "not found or forbidden"}), 404
    return None


@app.post("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_upload(station_id):
    err = _can_manage_station_or_404(station_id)
    if err: return err
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "file required"}), 400
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"}:
        return jsonify({"error": "unsupported audio format"}), 400
    try:
        every = max(1, min(int(request.form.get("every") or 5), 100))
    except ValueError:
        every = 5
    enabled = request.form.get("enabled", "1") != "0"
    os.makedirs(JINGLE_ROOT, exist_ok=True)
    target = os.path.join(JINGLE_ROOT, f"station_{station_id}{ext}")
    safe_target = _safe_data_path(target, JINGLE_ROOT)
    if safe_target is None:
        abort(400)
    for old_ext in (".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"):
        old = os.path.join(JINGLE_ROOT, f"station_{station_id}{old_ext}")
        if old != safe_target and os.path.exists(old):
            with contextlib.suppress(OSError):
                os.remove(old)
    file.save(safe_target)
    db.set_radio_station_jingle(station_id, safe_target, every, enabled)
    return jsonify(db.get_radio_station(station_id))


@app.patch("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_settings(station_id):
    err = _can_manage_station_or_404(station_id)
    if err: return err
    data = request.get_json(silent=True) or {}
    try:
        every = int(data.get("every") or 0)
    except (TypeError, ValueError):
        every = 0
    enabled = bool(data.get("enabled"))
    if not db.update_radio_station_jingle_settings(station_id, every, enabled):
        return jsonify({"error": "not found"}), 404
    return jsonify(db.get_radio_station(station_id))


@app.delete("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_delete(station_id):
    err = _can_manage_station_or_404(station_id)
    if err: return err
    path = db.get_radio_station_jingle_path(station_id, enabled_only=False)
    db.set_radio_station_jingle(station_id, None, 0, False)
    if path:
        safe = _safe_data_path(path, JINGLE_ROOT)
        if safe and os.path.exists(safe):
            with contextlib.suppress(OSError):
                os.remove(safe)
    return jsonify(db.get_radio_station(station_id))


@app.get("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_stream(station_id):
    path = db.get_radio_station_jingle_path(station_id)
    if not path:
        abort(404)
    safe = _safe_data_path(path, JINGLE_ROOT)
    if safe is None or not os.path.isfile(safe):
        abort(404)
    return send_file(safe, mimetype=_guess_mime(safe), conditional=True)


@app.get("/api/radio-stations/<int:station_id>/tracks")
def api_radio_station_tracks(station_id):
    started = _time.perf_counter()
    _touch_disco()
    count = min(_int_arg("count", 25, min_val=1, max_val=100), 100)
    exclude = [int(x) for x in request.args.getlist("exclude") if x.isdigit()]
    user_id = g.user["id"] if g.user else None
    station = db.get_radio_station(station_id)
    if (station and station.get("engine") == "adolar4u" and user_id
            and adolar4u.get_onboarding_state(user_id)["required"]):
        return jsonify({"error": "onboarding_required"}), 428
    token, shuffle_state = smart_shuffle.get_session(
        request.args.get("shuffle_session"),
        f"radio:{station_id}:user:{user_id or 0}",
    )
    with shuffle_state.lock:
        tracks = db.get_radio_station_tracks(
            station_id, count, exclude, user_id=user_id, shuffle_state=shuffle_state,
            recommendation_session_id=token,
        )
    if tracks is None:
        return jsonify({"error": "station not found"}), 404
    response = jsonify(tracks)
    response.headers["X-Shuffle-Session"] = token
    logging.getLogger(__name__).info(
        "radio queue station=%s count=%s duration_ms=%.1f",
        station_id, len(tracks), (_time.perf_counter() - started) * 1000,
    )
    return response


# ── Last.fm ───────────────────────────────────────────────────────────────────

def _lastfm_account():
    return db.get_lastfm_account(g.user["id"]) if g.user else None


def _lastfm_sync_state(user_id: int, job_type: str) -> dict:
    return db.get_lastfm_sync_state(user_id, job_type)


def _update_lastfm_sync_state(user_id: int, job_type: str, **values) -> dict:
    if "count" in values:
        values["result_count"] = values.pop("count")
    if "updated" in values:
        values["updated_count"] = values.pop("updated")
    return db.update_lastfm_sync_state(user_id, job_type, **values)

@app.get("/api/lastfm/status")
def api_lastfm_status():
    account = _lastfm_account()
    return jsonify({
        "connected": bool(account),
        "username": account["username"] if account else None,
        "auto_love_favorites": bool(account and account["auto_love_favorites"]),
    })


@app.get("/api/lastfm/auth")
def api_lastfm_auth():
    flask_session["lastfm_auth_user_id"] = g.user["id"]
    callback = request.host_url.rstrip("/") + "/api/lastfm/callback"
    url = lastfm.get_auth_url(callback)
    return redirect(url)


@app.get("/api/lastfm/callback")
def api_lastfm_callback():
    pending_user_id = flask_session.pop("lastfm_auth_user_id", None)
    if not g.user or pending_user_id != g.user["id"]:
        return "Last.fm Auth-Sitzung ist abgelaufen. Bitte erneut verbinden.", 400
    token = request.args.get("token")
    if not token:
        return "Kein Token erhalten.", 400
    try:
        session = lastfm.get_session(token)
        db.set_lastfm_account(g.user["id"], session["name"], session["key"])
    except Exception as e:
        logging.getLogger(__name__).warning("Last.fm Auth fehlgeschlagen (%s)", e)
        return "Last.fm Auth fehlgeschlagen. Bitte erneut verbinden.", 500

    username = html.escape(session.get("name") or "")
    return f"""<html><body style="font-family:sans-serif;padding:40px;background:#30302E;color:#ECECEC">
        <h2 style="color:#7F77DD">&#10003; Last.fm verbunden!</h2>
        <p>Du bist als <strong>{username}</strong> eingeloggt.</p>
        <p><a href="/" style="color:#7F77DD">Zur&#252;ck zur App</a></p>
    </body></html>"""


@app.post("/api/lastfm/disconnect")
def api_lastfm_disconnect():
    db.disconnect_lastfm_account(g.user["id"])
    return jsonify({"ok": True})


def _sync_lastfm_loved_tracks(user_id: int):
    account = db.get_lastfm_account(user_id)
    if not account:
        _update_lastfm_sync_state(user_id, "loved", running=False, error="not connected")
        return
    try:
        items = lastfm.get_loved_tracks(account["username"])
        count = db.replace_lastfm_loved_tracks(user_id, items)
        _update_lastfm_sync_state(
            user_id, "loved", running=False, error=None, count=count,
            finished_at=_time.time(),
        )
    except Exception as e:
        logging.getLogger(__name__).exception("Last.fm loved sync failed")
        _update_lastfm_sync_state(
            user_id, "loved", running=False, error=str(e), finished_at=_time.time(),
        )


@app.get("/api/lastfm/loved/status")
def api_lastfm_loved_status():
    status = db.get_lastfm_loved_status(g.user["id"])
    status.update(_lastfm_sync_state(g.user["id"], "loved"))
    status["connected"] = bool(_lastfm_account())
    return jsonify(status)


@app.post("/api/lastfm/loved/sync")
def api_lastfm_loved_sync():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    if not db.claim_lastfm_sync_job(g.user["id"], "loved"):
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_sync_lastfm_loved_tracks, args=(g.user["id"],))
    return jsonify({"ok": True, "message": "sync started"}), 202


def _sync_lastfm_playcounts(user_id: int):
    account = db.get_lastfm_account(user_id)
    if not account:
        _update_lastfm_sync_state(user_id, "playcounts", running=False, error="not connected")
        return
    log = logging.getLogger(__name__)
    try:
        user = _auth.get_user_by_id(user_id)
        contributes_archive = bool(
            user and (user.get("role") == "admin" or user.get("contributes_playcount"))
        )
        with db.db() as conn:
            tracks = conn.execute(
                "SELECT id, path, artist, title FROM tracks WHERE artist IS NOT NULL AND title IS NOT NULL"
            ).fetchall()
        total = len(tracks)
        _update_lastfm_sync_state(user_id, "playcounts", total=total, done=0)
        updated = 0
        for i, row in enumerate(tracks):
            if i == 0 or (i + 1) % 25 == 0 or i + 1 == total:
                _update_lastfm_sync_state(user_id, "playcounts", done=i + 1)
            try:
                pc = lastfm.get_user_track_playcount(
                    account["username"], row["artist"], row["title"]
                )
                if pc and pc > 0:
                    # Last.fm may raise personal and archive counts, never lower either.
                    with db.db() as conn:
                        conn.execute("""
                            INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
                            VALUES (?, ?, ?, NULL)
                            ON CONFLICT(user_id, track_id) DO UPDATE SET
                                count = MAX(count, excluded.count)
                        """, (user_id, row["id"], pc))
                    if contributes_archive and db.merge_archive_play_count(row["id"], pc):
                        updated += 1
            except Exception:
                log.debug("Playcount sync failed for %s - %s", row["artist"], row["title"])
        _update_lastfm_sync_state(
            user_id, "playcounts", running=False, error=None, done=total,
            updated=updated, finished_at=_time.time(),
        )
        with db.db() as conn:
            conn.execute(
                "UPDATE user_lastfm_accounts SET playcounts_synced_at=? WHERE user_id=?",
                (_time.time(), int(user_id)),
            )
    except Exception as e:
        log.exception("Last.fm playcount sync failed")
        _update_lastfm_sync_state(
            user_id, "playcounts", running=False, error=str(e),
            finished_at=_time.time(),
        )


@app.get("/api/lastfm/playcount/status")
def api_lastfm_pc_status():
    return jsonify(_lastfm_sync_state(g.user["id"], "playcounts"))


@app.post("/api/lastfm/playcount/sync")
def api_lastfm_pc_sync():
    if not _lastfm_account():
        return jsonify({"error": "not connected"}), 401
    if not db.claim_lastfm_sync_job(g.user["id"], "playcounts"):
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_sync_lastfm_playcounts, args=(g.user["id"],))
    return jsonify({"ok": True, "message": "sync started"})


@app.post("/api/lastfm/nowplaying")
def api_lastfm_nowplaying():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    queued = _submit_lastfm_call(
        "now_playing", lastfm.now_playing,
        account["session_key"], artist, title, duration=body.get("duration"),
    )
    return jsonify({"ok": True, "queued": queued}), 202


@app.post("/api/lastfm/scrobble")
def api_lastfm_scrobble():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    queued = _submit_lastfm_call(
        "scrobble", lastfm.scrobble, account["session_key"], artist, title,
        retries=1,
    )
    return jsonify({"ok": True, "queued": queued}), 202


@app.post("/api/lastfm/love")
def api_lastfm_love():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    action = body.get("action", "love")
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    try:
        if action == "love":
            lastfm.love(account["session_key"], artist, title)
            db.set_lastfm_loved(g.user["id"], artist, title, True)
        else:
            lastfm.unlove(account["session_key"], artist, title)
            db.set_lastfm_loved(g.user["id"], artist, title, False)
        return jsonify({"ok": True, "loved": action == "love"})
    except Exception:
        logging.getLogger(__name__).exception("Last.fm love/unlove failed")
        return jsonify({"error": "Last.fm request failed"}), 500


@app.get("/api/lastfm/loved")
def api_lastfm_loved():
    account = _lastfm_account()
    if not account:
        return jsonify({"loved": False})
    artist = request.args.get("artist", "")
    title  = request.args.get("title", "")
    try:
        info = lastfm.get_track_info(account["session_key"], artist, title)
        loved = str(info.get("userloved", "0")) == "1"
        return jsonify({"loved": loved})
    except Exception:
        return jsonify({"loved": False})


@app.patch("/api/lastfm/settings")
def api_lastfm_settings():
    data = request.get_json(silent=True) or {}
    if set(data) - {"auto_love_favorites"}:
        return jsonify({"error": "invalid setting"}), 400
    enabled = data.get("auto_love_favorites")
    if not isinstance(enabled, bool):
        return jsonify({"error": "auto_love_favorites must be boolean"}), 400
    if not db.set_lastfm_auto_love(g.user["id"], enabled):
        return jsonify({"error": "not connected"}), 404
    return jsonify({"ok": True, "auto_love_favorites": enabled})


# ── Scanner ───────────────────────────────────────────────────────────────────

@app.post("/api/scan/start")
@_auth.admin_required
def api_scan_start():
    music_root = _current_music_root()
    data = request.get_json(silent=True) or {}
    path_input = (data.get("path") or "").strip()
    if path_input:
        # Folder-scoped scan (e.g. triggered by Adolar Taggster after an
        # edit) — skips the full-library BPM/thumbnail follow-up sweeps.
        candidate = os.path.realpath(path_input)
        if candidate != music_root and not candidate.startswith(music_root + os.sep):
            return jsonify({"error": "path liegt nicht innerhalb der aktiven Bibliothek."}), 400
        if not os.path.isdir(candidate):
            return jsonify({"error": f"Pfad nicht gefunden: {candidate}"}), 400
        scanner.run_scan(candidate, run_followups=False)
        return jsonify({"status": "started", "path": candidate})
    if not os.path.isdir(music_root):
        return jsonify({"error": f"MUSIC_ROOT not found: {music_root}"}), 400
    scanner.run_scan(music_root)
    return jsonify({"status": "started"})


@app.post("/api/scan/bpm-tags")
@_auth.admin_required
def api_bpm_tags():
    """Read BPM from file tags (TBPM etc.) and update DB — fast, no audio analysis."""
    def _worker():
        task_id = tasks.start("bpm_tags", "manual")
        failed = False
        updated = 0
        total = 0
        try:
            from .db import get_connection
            conn = get_connection()
            rows = conn.execute("SELECT id, path FROM tracks").fetchall()
            conn.close()
            total = len(rows)
            tasks.update(task_id, total=total)
            for i, row in enumerate(rows):
                tasks.update(task_id, current=i + 1)
                try:
                    bpm = scanner._read_bpm_tag(row["path"])
                    if bpm and bpm > 0:
                        c = get_connection()
                        c.execute("UPDATE tracks SET bpm=? WHERE id=?", (bpm, row["id"]))
                        c.commit()
                        c.close()
                        updated += 1
                except Exception:
                    pass
        except Exception as e:
            logging.getLogger(__name__).error("bpm-tags: %s", e)
            failed = True
        finally:
            tasks.finish(
                task_id, status="failed" if failed else "completed",
                detail=f"{updated} von {total} aktualisiert" if total else None,
            )
    _start_library_thread(_worker)
    return jsonify({"status": "started", "updated": 0, "note": "running in background"})


@app.post("/api/scan/bpm")
@_auth.admin_required
def api_bpm_scan():
    """Trigger background BPM analysis for tracks without BPM.
    Optional JSON body: {"limit": 500} to cap the number analysed."""
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit", 0))
    scanner.run_bpm_scan(limit)
    return jsonify({"status": "started", "limit": limit or "unlimited"})


@app.get("/api/scan/status")
def api_scan_status():
    s = scanner.status()
    persisted = db.get_scanner_status()
    s["total_tracks"] = persisted["total_tracks"]
    s["finished_at"] = s.get("finished_at") or persisted.get("finished_at")
    return jsonify(s)


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
                    _flush_play_count_tags()
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
                        _run_backup_job("automatic")
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
