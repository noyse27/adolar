"""Library scan and BPM maintenance routes."""

import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from .. import auth as _auth
from .. import db, scanner, tasks
from ..application import _current_music_root, _start_library_thread

blueprint = Blueprint("scanner", __name__)


def _library_scoped_directory(path_input: str, music_root: str) -> tuple[str | None, str | None]:
    try:
        root = Path(music_root).resolve(strict=True)
    except OSError:
        return None, "missing"
    try:
        raw = Path(path_input)
        candidate = raw.resolve(strict=True) if raw.is_absolute() else (root / raw).resolve(strict=True)
    except OSError:
        return None, "missing"
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "outside"
    if not candidate.is_dir():
        return None, "missing"
    return os.fspath(candidate), None


# ── Scanner ───────────────────────────────────────────────────────────────────

@blueprint.post("/api/scan/start")
@_auth.admin_required
def api_scan_start():
    music_root = _current_music_root()
    data = request.get_json(silent=True) or {}
    path_input = (data.get("path") or "").strip()
    force = bool(data.get("force"))
    if path_input:
        # Folder-scoped scan (e.g. triggered by Adolar Taggster after an
        # edit) — skips the full-library BPM/thumbnail follow-up sweeps.
        candidate, path_error = _library_scoped_directory(path_input, music_root)
        if candidate is None:
            if path_error == "missing":
                return jsonify({"error": f"Pfad nicht gefunden: {path_input}"}), 400
            return jsonify({"error": "path liegt nicht innerhalb der aktiven Bibliothek."}), 400
        scanner.run_scan(candidate, run_followups=False, force=force)
        return jsonify({"status": "started", "path": candidate})
    if not os.path.isdir(music_root):
        return jsonify({"error": f"MUSIC_ROOT not found: {music_root}"}), 400
    scanner.run_scan(music_root, force=force)
    return jsonify({"status": "started"})


@blueprint.post("/api/scan/bpm-tags")
@_auth.admin_required
def api_bpm_tags():
    """Read BPM from file tags (TBPM etc.) and update DB — fast, no audio analysis."""
    def _worker():
        task_id = tasks.start("bpm_tags", "manual")
        failed = False
        updated = 0
        total = 0
        try:
            from ..db import get_connection
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


@blueprint.post("/api/scan/bpm")
@_auth.admin_required
def api_bpm_scan():
    """Trigger background BPM analysis for tracks without BPM.
    Optional JSON body: {"limit": 500} to cap the number analysed."""
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit", 0))
    scanner.run_bpm_scan(limit)
    return jsonify({"status": "started", "limit": limit or "unlimited"})


@blueprint.get("/api/scan/status")
def api_scan_status():
    s = scanner.status()
    persisted = db.get_scanner_status()
    s["total_tracks"] = persisted["total_tracks"]
    s["finished_at"] = s.get("finished_at") or persisted.get("finished_at")
    return jsonify(s)
