"""Administration, monitoring, backup, and library-management routes."""

import ipaddress
import json
import logging
import os
import sqlite3
import time as _time
from pathlib import Path

import psutil
from flask import Blueprint, abort, g, jsonify, request, send_file

from .. import application as core
from .. import auth as _auth
from .. import backup_service, db, errors, libraries, library_context, scanner, tasks
from ..application import (
    _backup_auto_enabled,
    _backup_hour,
    _backup_retention,
    _backup_root,
    _client_error,
    _current_music_root,
    _int_arg,
    _start_library_thread,
)

blueprint = Blueprint("admin", __name__)


def _trusted_admin_directory(raw_path: str) -> str:
    """Resolve an admin-configured host directory before it is persisted."""
    # Admin users are allowed to choose arbitrary host directories for library
    # roots; this validates that the chosen target already exists and is a
    # directory before storing the canonical path.
    resolved = Path(raw_path).expanduser().resolve(strict=True)  # codeql[py/path-injection]
    if not resolved.is_dir():
        raise errors.ValidationError("Der angegebene Pfad existiert nicht oder ist kein Verzeichnis.")
    return os.fspath(resolved)


@blueprint.get("/api/admin/audit-log")
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


@blueprint.post("/api/client/heartbeat")
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
    and run_backup_job) rather than going through tasks.py, since that also
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


@blueprint.get("/api/admin/monitor")
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

def run_backup_job(source: str, actor_id: int | None = None):
    try:
        result = backup_service.create_backup(
            db.current_db_path(),
            _backup_root(),
            control_db_path=db.CONTROL_DB_PATH,
            jingle_root=core.JINGLE_ROOT,
            app_version=core.APP_VERSION,
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
        run_backup_job,
        args=(source, actor_id),
        name=f"adolar-backup-{source}",
    )
    return True


@blueprint.get("/api/admin/backups")
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


@blueprint.put("/api/admin/backups/config")
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


@blueprint.post("/api/admin/backups")
@_auth.admin_required
def api_backups_create():
    try:
        backup_service.ensure_backup_root(_backup_root())
    except OSError as exc:
        return _client_error("Backup-Ziel nicht beschreibbar.", exc, 503)
    if not _start_backup_job("manual", g.user["id"]):
        return jsonify({"error": "Eine Datensicherung läuft bereits."}), 409
    return jsonify({"status": "started"}), 202


@blueprint.get("/api/admin/backups/<backup_id>/<kind>")
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


@blueprint.delete("/api/admin/backups/<backup_id>")
@_auth.admin_required
def api_backups_delete(backup_id):
    try:
        backup_service.delete_backup(_backup_root(), backup_id)
    except FileNotFoundError:
        abort(404)
    db.log_audit(g.user["id"], "backup.deleted", backup_id)
    return jsonify({"ok": True})


# ── Library management (admin only) ────────────────────────────────────────────

@blueprint.get("/api/admin/libraries")
@_auth.admin_required
def api_libraries_list():
    libs, active_id = libraries.list_libraries(
        core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH,
    )
    return jsonify({"libraries": libs, "active_id": active_id})


@blueprint.post("/api/admin/libraries")
@_auth.admin_required
def api_libraries_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    music_path_input = (data.get("music_path") or "").strip()
    try:
        if not name:
            raise errors.ValidationError("Bitte einen Namen für die Bibliothek angeben.")
        if not music_path_input:
            raise errors.ValidationError("Der angegebene Pfad existiert nicht oder ist kein Verzeichnis.")
        music_path = _trusted_admin_directory(music_path_input)
    except OSError as exc:
        return _client_error("Der angegebene Pfad existiert nicht oder ist kein Verzeichnis.", exc)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    lib = libraries.add_library(
        core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH,
        core.LIBRARIES_DIR, name, music_path,
    )
    with library_context.bind(lib["db_path"], lib["music_path"]):
        db.init_db()
        db.log_audit(g.user["id"], "library.created", lib["id"], json.dumps(lib))
    return jsonify(lib), 201


@blueprint.post("/api/admin/libraries/<library_id>/activate")
@_auth.admin_required
def api_libraries_activate(library_id):
    try:
        lib = libraries.set_active(core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH, library_id)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc, 404)
    with library_context.bind(lib["db_path"], lib["music_path"]):
        db.init_db()
        db.log_audit(g.user["id"], "library.activated", lib["id"])
    return jsonify(lib)


@blueprint.put("/api/admin/libraries/<library_id>/move")
@_auth.admin_required
def api_libraries_move(library_id):
    _libs, active_id = libraries.list_libraries(core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH)
    data = request.get_json(silent=True) or {}
    new_music_path_input = (data.get("new_music_path") or "").strip()
    try:
        if library_id != active_id:
            raise errors.ValidationError("Bitte zuerst diese Bibliothek aktivieren, bevor sie umgezogen wird.")
        if not new_music_path_input:
            raise errors.ValidationError("Der neue Pfad existiert nicht oder ist kein Verzeichnis.")
        new_music_path = _trusted_admin_directory(new_music_path_input)
    except OSError as exc:
        return _client_error("Der neue Pfad existiert nicht oder ist kein Verzeichnis.", exc)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    old_music_path = _current_music_root()
    updated = db.migrate_track_paths(old_music_path, new_music_path)
    lib = libraries.update_music_path(
        core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH, library_id, new_music_path,
    )
    db.log_audit(
        g.user["id"], "library.moved", library_id,
        json.dumps({"old_path": old_music_path, "new_path": new_music_path, "tracks_updated": updated}),
    )
    return jsonify({"library": lib, "tracks_updated": updated})


@blueprint.post("/api/admin/libraries/<library_id>/rename-path")
@_auth.admin_required
def api_libraries_rename_path(library_id):
    """Rewrite tracks.path for a subfolder rename/move within the active
    library. Unlike /move above, this does NOT touch the library's
    registered music_path — only the DB rows under old_path are rewritten.
    Intended for external tools (e.g. Adolar Taggster) that rename/move a
    folder on disk themselves and just need Adolar's DB kept in sync."""
    _libs, active_id = libraries.list_libraries(core.LIBRARY_REGISTRY_PATH, core.MUSIC_ROOT, db.DB_PATH)
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


@blueprint.post("/api/admin/library/covers")
@_auth.admin_required
def api_library_covers():
    """Generate thumbnails for cover art already found on disk/in tags.

    This does not re-read tags from files that a normal scan considers
    unchanged; use "Bibliothek neu scannen" for that.
    """
    scanner.run_thumb_generation()
    return jsonify({"status": "started"})


@blueprint.post("/api/admin/database/optimize")
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
