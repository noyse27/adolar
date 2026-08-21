"""Cover art, streaming, downloads, and play-count routes."""

import logging
import os
import threading
import time as _time

from flask import Blueprint, abort, g, jsonify, make_response, request, send_file
from werkzeug.http import http_date

from .. import application as core
from .. import auth as _auth
from .. import db
from ..application import _safe_path, _start_library_thread, _touch_disco

blueprint = Blueprint("media", __name__)

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


@blueprint.get("/api/cover/<hash_>")
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

@blueprint.get("/api/stream/<int:track_id>")
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
    mime = guess_mime(path)

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


def guess_mime(path):
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

@blueprint.post("/api/download")
def api_download():
    if not _auth.can(g.user, "download_tracks"):
        return jsonify({"error": "Download nicht erlaubt."}), 403
    import io
    import time
    import zipfile
    ids = request.json.get("ids", [])
    if not ids:
        return jsonify({"error": "no ids"}), 400
    if len(ids) > core.MAX_DOWNLOAD_IDS:
        return jsonify({"error": f"too many ids (max {core.MAX_DOWNLOAD_IDS})"}), 400

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

@blueprint.post("/api/track/<int:track_id>/bpm")
def api_track_bpm(track_id):
    """Accept a BPM value from an external tool. Called by Adolar Disco without
    a session, like /disco-played — see auth.PUBLIC_TRACK_SUFFIXES."""
    data = request.get_json(silent=True) or {}
    bpm = data.get("bpm")
    if bpm is None or not isinstance(bpm, (int, float)) or bpm <= 0:
        return jsonify({"error": "bpm must be a positive number"}), 400
    updated = db.update_bpm(track_id, round(float(bpm), 2))
    return jsonify({"ok": True, "updated": updated})


@blueprint.post("/api/track/<int:track_id>/played")
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


@blueprint.post("/api/track/<int:track_id>/disco-played")
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


def flush_play_count_tags():
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


@blueprint.get("/api/playcount-tags/status")
@_auth.admin_required
def api_play_count_tags_status():
    return jsonify({**db.get_play_count_tag_status(), **_play_count_tag_sync})


@blueprint.post("/api/playcount-tags/sync")
@_auth.admin_required
def api_play_count_tags_sync():
    if _play_count_tag_sync["running"]:
        return jsonify({"error": "already running"}), 409
    _start_library_thread(flush_play_count_tags)
    return jsonify({"ok": True})
