"""Optional lyrics API and its background lookup jobs."""

import logging
import threading
import time as _time
import urllib.error

from flask import Blueprint, abort, g, jsonify, request

from .. import auth as _auth
from .. import db, lyrics, tasks
from ..application import _client_error, _start_library_thread

blueprint = Blueprint("lyrics", __name__)

# ── Optional lyrics module ───────────────────────────────────────────────────

_lyrics_job_lock = threading.Lock()
_lyrics_track_jobs: set[int] = set()
_lyrics_scan_running = False


def _public_lyrics_payload(row: dict | None, user=None) -> dict:
    module_enabled = lyrics.enabled()
    if row is None:
        return {
            "enabled": module_enabled, "available": False,
            "status": "missing" if module_enabled else "disabled",
            "editable": module_enabled and _auth.can(user, "edit_lyrics"),
        }
    return {
        "enabled": module_enabled,
        "track_id": row["track_id"],
        "title": row.get("title"),
        "artist": row.get("artist"),
        "album": row.get("album"),
        "available": module_enabled and bool(row.get("available")),
        "instrumental": bool(row.get("instrumental")),
        "status": row.get("status") if module_enabled else "disabled",
        "format": row.get("format") or ("lrc" if row.get("synced_lyrics") else "plain"),
        "plain_lyrics": (row.get("plain_lyrics") or "") if module_enabled else "",
        "synced_lyrics": (row.get("synced_lyrics") or "") if module_enabled else "",
        "lines": (row.get("lines") or []) if module_enabled else [],
        "source": row.get("source") if module_enabled else None,
        "checked_at": row.get("checked_at"),
        "next_check_at": row.get("next_check_at"),
        "revision": int(row.get("revision") or 1),
        "sync_state": row.get("sync_state") or "clean",
        "editable": module_enabled and _auth.can(user, "edit_lyrics"),
    }


def _schedule_lyrics_track(track_id: int, *, force: bool = False) -> bool:
    track_id = int(track_id)
    with _lyrics_job_lock:
        if track_id in _lyrics_track_jobs:
            return False
        _lyrics_track_jobs.add(track_id)

    def worker():
        try:
            lyrics.resolve_track(track_id, force=force)
        finally:
            with _lyrics_job_lock:
                _lyrics_track_jobs.discard(track_id)

    _start_library_thread(worker, name=f"adolar-lyrics-{track_id}")
    return True


def start_scan(trigger: str = "manual", *, force: bool = False) -> bool:
    global _lyrics_scan_running
    with _lyrics_job_lock:
        if _lyrics_scan_running:
            return False
        _lyrics_scan_running = True

    def worker():
        global _lyrics_scan_running
        task_id = tasks.start("lyrics_scan", trigger)
        checked = found = failed = 0
        try:
            lyrics.ensure_all_rows()
            with db.db() as conn:
                if force:
                    rows = conn.execute(
                        "SELECT track_id FROM track_lyrics ORDER BY track_id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT track_id FROM track_lyrics
                           WHERE status='pending'
                              OR (status IN ('missing','error')
                                  AND COALESCE(next_check_at,0) <= ?)
                           ORDER BY track_id""",
                        (_time.time(),),
                    ).fetchall()
            tasks.update(task_id, total=len(rows))
            for index, row in enumerate(rows, 1):
                tasks.update(task_id, current=index)
                result = lyrics.resolve_track(row["track_id"], force=force)
                checked += 1
                if result and result.get("available"):
                    found += 1
                elif result and result.get("status") == "error":
                    failed += 1
        except Exception:
            failed += 1
            logging.getLogger(__name__).exception("Lyrics scan failed")
        finally:
            tasks.finish(
                task_id,
                status="failed" if failed and not checked else "completed",
                detail=f"{found} von {checked} mit Lyrics, {failed} Fehler",
            )
            with _lyrics_job_lock:
                _lyrics_scan_running = False

    _start_library_thread(worker, name="adolar-lyrics-scan")
    return True


@blueprint.get("/api/lyrics/status")
def api_lyrics_status():
    return jsonify({
        "enabled": lyrics.enabled(),
        "auto_fetch": lyrics.auto_fetch_enabled(),
    })


@blueprint.get("/api/tracks/<int:track_id>/lyrics")
def api_track_lyrics_get(track_id):
    row = lyrics.get_track_lyrics(track_id)
    if row is None:
        abort(404)
    return jsonify(_public_lyrics_payload(row, g.user))


@blueprint.post("/api/tracks/<int:track_id>/lyrics/fetch")
def api_track_lyrics_fetch(track_id):
    row = lyrics.get_track_lyrics(track_id)
    if row is None:
        abort(404)
    if not lyrics.enabled():
        return jsonify(_public_lyrics_payload(row, g.user)), 409
    if row.get("available") and not request.args.get("force"):
        return jsonify(_public_lyrics_payload(row, g.user))
    scheduled = _schedule_lyrics_track(
        track_id, force=request.args.get("force") == "1" and bool(
            g.user and g.user.get("role") == "admin"
        ),
    )
    return jsonify({"scheduled": scheduled, "status": row["status"]}), 202


@blueprint.post("/api/tracks/<int:track_id>/lyrics/search")
def api_track_lyrics_search(track_id):
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    if not lyrics.enabled():
        return jsonify({"error": "Lyrics-Modul ist deaktiviert."}), 409
    if not _auth.can(g.user, "edit_lyrics"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        results = lyrics.search_provider_candidates(
            track_id,
            title=data.get("title"),
            artist=data.get("artist"),
            album=data.get("album"),
        )
    except LookupError:
        abort(404)
    except lyrics.LyricsValidationError as exc:
        return _client_error(exc.user_message, exc)
    except Exception:
        logging.getLogger(__name__).exception(
            "Manual lyrics search failed for track %s", track_id,
        )
        return jsonify({"error": "Lyrics-Anbieter ist derzeit nicht erreichbar."}), 502
    return jsonify({"results": results})


@blueprint.post("/api/tracks/<int:track_id>/lyrics/select")
def api_track_lyrics_select(track_id):
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    if not lyrics.enabled():
        return jsonify({"error": "Lyrics-Modul ist deaktiviert."}), 409
    if not _auth.can(g.user, "edit_lyrics"):
        return jsonify({"error": "forbidden"}), 403
    source_id = str((request.get_json(silent=True) or {}).get("source_id") or "")
    try:
        row = lyrics.apply_provider_candidate(track_id, source_id)
    except LookupError:
        abort(404)
    except lyrics.LyricsValidationError as exc:
        return _client_error(exc.user_message, exc)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return jsonify({"error": "Der gewählte Lyrics-Treffer existiert nicht mehr."}), 404
        return jsonify({"error": "Lyrics-Anbieter ist derzeit nicht erreichbar."}), 502
    except Exception:
        logging.getLogger(__name__).exception(
            "Selected lyrics download failed for track %s", track_id,
        )
        return jsonify({"error": "Lyrics-Anbieter ist derzeit nicht erreichbar."}), 502
    db.log_audit(g.user["id"], "lyrics.provider_replaced", f"track:{track_id}")
    return jsonify(_public_lyrics_payload(row, g.user))


@blueprint.put("/api/tracks/<int:track_id>/lyrics")
def api_track_lyrics_put(track_id):
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    if not lyrics.enabled():
        return jsonify({"error": "Lyrics-Modul ist deaktiviert."}), 409
    if not _auth.can(g.user, "edit_lyrics"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        revision = int(data.get("revision"))
        row = lyrics.update_track_lyrics(
            track_id,
            content=data.get("content", ""),
            format_=str(data.get("format") or "plain"),
            expected_revision=revision,
            user_id=g.user["id"],
        )
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Lyrics-Revision."}), 400
    except lyrics.LyricsValidationError as exc:
        return _client_error(exc.user_message, exc)
    except lyrics.LyricsConflict as exc:
        return _client_error(exc.user_message, exc, 409)
    except LookupError:
        abort(404)
    db.log_audit(g.user["id"], "lyrics.updated", f"track:{track_id}")
    return jsonify(_public_lyrics_payload(row, g.user))


@blueprint.get("/api/admin/lyrics/settings")
@_auth.admin_required
def api_lyrics_admin_settings_get():
    return jsonify(lyrics.get_settings(include_secret_state=True))


@blueprint.put("/api/admin/lyrics/settings")
@_auth.admin_required
def api_lyrics_admin_settings_put():
    data = request.get_json(silent=True) or {}
    was_enabled = lyrics.enabled()
    try:
        settings = lyrics.update_settings(data)
    except lyrics.LyricsValidationError as exc:
        return _client_error(exc.user_message, exc)
    db.log_audit(g.user["id"], "lyrics.settings_updated", "system")
    if settings["enabled"] and not was_enabled:
        with db.db() as conn:
            conn.execute(
                """UPDATE track_lyrics SET next_check_at=0
                   WHERE status IN ('missing','error')"""
            )
        start_scan("module_enabled")
    return jsonify(settings)


@blueprint.post("/api/admin/lyrics/scan")
@_auth.admin_required
def api_lyrics_admin_scan():
    if not lyrics.enabled():
        return jsonify({"error": "Lyrics-Modul ist deaktiviert."}), 409
    started = start_scan(
        "manual", force=bool((request.get_json(silent=True) or {}).get("force", False)),
    )
    return jsonify({"started": started}), 202 if started else 409
