import os
import html
import logging
from flask import Flask, jsonify, request, send_file, abort, render_template, redirect, make_response, g
from flask_cors import CORS
import db
import scanner
import lastfm
import auth as _auth

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))

# Restrict CORS to origins defined via env var (space-separated).
# Default: deny all cross-origin requests (safe for local NAS use).
_cors_origins = os.environ.get("CORS_ORIGINS", "")
CORS(app, origins=_cors_origins.split() if _cors_origins else [])

app.before_request(_auth.before_request)

MUSIC_ROOT = os.environ.get("MUSIC_ROOT", "/music")
MAX_DOWNLOAD_IDS = int(os.environ.get("MAX_DOWNLOAD_IDS", 500))

# ── Adolar Disco connection tracking ─────────────────────────────────────────
import time as _time
_disco_last_seen: float = 0   # epoch seconds
_DISCO_TIMEOUT = 120          # seconds until considered disconnected

def _touch_disco():
    global _disco_last_seen
    _disco_last_seen = _time.time()

def _disco_active() -> bool:
    return (_time.time() - _disco_last_seen) < _DISCO_TIMEOUT


def _safe_path(path: str) -> str | None:
    """Resolve path and verify it stays within MUSIC_ROOT. Returns None if outside."""
    if not os.path.isabs(path):
        path = os.path.join(MUSIC_ROOT, path)
    real   = os.path.realpath(path)
    root   = os.path.realpath(MUSIC_ROOT)
    if not real.startswith(root + os.sep) and real != root:
        return None
    return real


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


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/setup")
def setup_get():
    if _auth.user_count() > 0:
        return redirect("/login")
    return render_template("setup.html", error=None, username="")

@app.post("/setup")
def setup_post():
    if _auth.user_count() > 0:
        return redirect("/")
    username  = request.form.get("username", "").strip()
    password  = request.form.get("password", "")
    password2 = request.form.get("password2", "")
    err = None
    if not username:
        err = "Benutzername darf nicht leer sein."
    elif len(password) < 8:
        err = "Passwort muss mindestens 8 Zeichen haben."
    elif password != password2:
        err = "Passwörter stimmen nicht überein."
    if err:
        return render_template("setup.html", error=err, username=username)
    user_id = _auth.create_user(username, password, role="admin")
    # Admin doesn't need to change password on first login
    with db.db() as conn:
        conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (user_id,))
    token = _auth.create_session(user_id, remember=False)
    resp = make_response(redirect("/"))
    resp.set_cookie(_auth.SESSION_COOKIE, token, httponly=True, samesite="Lax", max_age=_auth.SESSION_TTL)
    return resp


@app.get("/login")
def login_get():
    if _auth.user_count() == 0:
        return redirect("/setup")
    ip = _auth._get_client_ip()
    blocked, secs = _auth._bf_check(ip)
    return render_template("login.html",
                           error=None, username="",
                           next=request.args.get("next", "/"),
                           blocked=blocked, blocked_seconds=secs)

@app.post("/login")
def login_post():
    if _auth.user_count() == 0:
        return redirect("/setup")
    ip = _auth._get_client_ip()
    blocked, secs = _auth._bf_check(ip)
    if blocked:
        return render_template("login.html", error=None, username="",
                               next=request.form.get("next", "/"),
                               blocked=True, blocked_seconds=secs), 429

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    remember = bool(request.form.get("remember"))
    next_url = request.form.get("next", "/") or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    user = _auth.get_user_by_name(username)
    if not user or not _auth.verify_password(user, password):
        _auth._bf_record_failure(ip)
        blocked2, secs2 = _auth._bf_check(ip)
        err = "Ungültiger Benutzername oder Passwort."
        return render_template("login.html", error=err, username=username,
                               next=next_url, blocked=blocked2, blocked_seconds=secs2), 401

    _auth._bf_clear(ip)
    token = _auth.create_session(user["id"], remember)
    max_age = _auth.SESSION_TTL_LONG if remember else _auth.SESSION_TTL
    resp = make_response(redirect(next_url))
    resp.set_cookie(_auth.SESSION_COOKIE, token, httponly=True, samesite="Lax", max_age=max_age)
    return resp


@app.post("/logout")
def logout():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    if token:
        _auth.delete_session(token)
    resp = make_response(redirect("/login"))
    resp.delete_cookie(_auth.SESSION_COOKIE)
    return resp


@app.get("/change-password")
def change_password_get():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user = _auth.get_user_by_token(token) if token else None
    if not user:
        return redirect("/login")
    forced = bool(user["must_change_password"])
    return render_template("change_password.html", error=None, forced=forced)

@app.post("/api/auth/change-password")
def api_change_password():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user = _auth.get_user_by_token(token) if token else None
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    data      = request.get_json(silent=True) or {}
    password  = data.get("password", "")
    password2 = data.get("password2", "")
    old_pw    = data.get("old_password", "")
    forced    = bool(user["must_change_password"])

    if not forced:
        full_user = _auth.get_user_by_name(user["username"])
        if not _auth.verify_password(full_user, old_pw):
            return jsonify({"error": "Aktuelles Passwort falsch."}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    if password != password2:
        return jsonify({"error": "Passwörter stimmen nicht überein."}), 400
    _auth.set_password(user["id"], password, must_change=False)
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    is_admin = g.user["role"] == "admin"
    return jsonify({
        "id":             g.user["id"],
        "username":       g.user["username"],
        "role":           g.user["role"],
        "allow_download": is_admin or bool(g.user["allow_download"]),
    })


# ── User management (admin only) ──────────────────────────────────────────────

@app.get("/api/users")
@_auth.admin_required
def api_users_list():
    return jsonify(_auth.get_all_users())

@app.post("/api/users")
@_auth.admin_required
def api_users_create():
    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password", "")
    if not username:
        return jsonify({"error": "Benutzername fehlt."}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    if _auth.get_user_by_name(username):
        return jsonify({"error": "Benutzername bereits vergeben."}), 409
    uid = _auth.create_user(username, password, role="user")
    return jsonify({"ok": True, "id": uid}), 201

@app.delete("/api/users/<int:user_id>")
@_auth.admin_required
def api_users_delete(user_id):
    if user_id == g.user["id"]:
        return jsonify({"error": "Eigenen Account nicht löschbar."}), 400
    _auth.delete_user(user_id)
    return jsonify({"ok": True})

@app.post("/api/users/<int:user_id>/password")
@_auth.admin_required
def api_users_set_password(user_id):
    data     = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    _auth.set_password(user_id, password, must_change=True)
    return jsonify({"ok": True})

@app.post("/api/users/<int:user_id>/download")
@_auth.admin_required
def api_users_set_download(user_id):
    data  = request.get_json(silent=True) or {}
    allow = bool(data.get("allow", False))
    _auth.set_allow_download(user_id, allow)
    return jsonify({"ok": True, "allow_download": allow})

@app.get("/api/me-optional")
def api_me_optional():
    """Like /api/me but returns null instead of 401 — used by Radio Companion."""
    token = request.cookies.get(_auth.SESSION_COOKIE)
    if token:
        user = _auth.get_user_by_token(token)
        if user:
            is_admin = user["role"] == "admin"
            return jsonify({
                "id":             user["id"],
                "username":       user["username"],
                "role":           user["role"],
                "allow_download": is_admin or bool(user["allow_download"]),
            })
    return jsonify(None)


@app.post("/api/radio/bookmark/<int:track_id>")
def api_radio_bookmark(track_id):
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user  = _auth.get_user_by_token(token) if token else None
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    with db.db() as conn:
        if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone():
            abort(404)
    pl_id = db.get_or_create_radio_favorites(user["id"])
    db.add_track_to_playlist(pl_id, track_id)
    return jsonify({"ok": True, "playlist_id": pl_id})


@app.get("/api/playlists/memberships")
def api_playlist_memberships():
    ids_raw = request.args.get("ids", "")
    try:
        track_ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    except ValueError:
        return jsonify({}), 400
    return jsonify(db.get_track_playlist_memberships(g.user["id"], track_ids))


@app.post("/api/playlists/<int:playlist_id>/tracks")
def api_playlist_add_track(playlist_id):
    data     = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if not isinstance(track_id, int):
        return jsonify({"error": "track_id fehlt."}), 400
    # Verify ownership
    pl = db.get_user_by_id(g.user["id"])  # just check user exists
    with db.db() as conn:
        row = conn.execute(
            "SELECT id FROM playlists WHERE id=? AND owner_id=?",
            (playlist_id, g.user["id"])
        ).fetchone()
    if not row:
        return jsonify({"error": "Playlist nicht gefunden."}), 404
    db.add_track_to_playlist(playlist_id, track_id)
    return jsonify({"ok": True})


@app.get("/api/playlists/<int:playlist_id>/tracks")
def api_playlist_tracks(playlist_id):
    tracks = db.get_playlist_tracks(playlist_id, g.user["id"])
    if tracks is None:
        return jsonify({"error": "Nicht gefunden."}), 404
    return jsonify(tracks)


@app.get("/api/playlists")
def api_playlists_list():
    return jsonify(db.get_playlists(g.user["id"]))

@app.post("/api/playlists")
def api_playlists_create():
    import json
    data    = request.get_json(silent=True) or {}
    name    = (data.get("name") or "").strip()
    type_   = data.get("type", "smart")
    filters = data.get("filters", {})
    sort    = data.get("sort", "artist")
    if not name:
        return jsonify({"error": "Name fehlt."}), 400
    pid = db.create_playlist(g.user["id"], name, json.dumps(filters), sort, type_)
    return jsonify({"ok": True, "id": pid}), 201

@app.delete("/api/playlists/<int:playlist_id>")
def api_playlists_delete(playlist_id):
    if not db.delete_playlist(playlist_id, g.user["id"]):
        return jsonify({"error": "Nicht gefunden oder keine Berechtigung."}), 404
    return jsonify({"ok": True})

@app.patch("/api/playlists/<int:playlist_id>")
def api_playlists_rename(playlist_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name fehlt."}), 400
    if not db.rename_playlist(playlist_id, g.user["id"], name):
        return jsonify({"error": "Nicht gefunden oder keine Berechtigung."}), 404
    return jsonify({"ok": True})


@app.get("/api/admin/blocked-ips")
@_auth.admin_required
def api_blocked_ips():
    return jsonify(_auth.get_blocked_ips())

@app.delete("/api/admin/blocked-ips/<path:ip>")
@_auth.admin_required
def api_unblock_ip(ip):
    _auth.unblock_ip(ip)
    return jsonify({"ok": True})


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["HEAD"])
def index_head():
    return "", 200

@app.get("/")
def index():
    if _auth.user_count() == 0:
        return redirect("/setup")
    return render_template("index.html")


@app.get("/miniplayer")
def miniplayer():
    return render_template("miniplayer.html")


@app.get("/radio")
def radio_companion():
    return render_template("radio.html")


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
        genre=genre, decade=decade, fmt=fmt,
        min_dur=min_dur, max_dur=max_dur, min_bitrate=min_bitrate,
        year_min=year_min, year_max=year_max,
        bpm_min=bpm_min, bpm_max=bpm_max,
        page=page, per_page=per_page, sort=sort, count=do_count,
        loved_only=loved, include_loved=bool(db.get_setting("lastfm_session_key")),
        user_id=user_id,
    )
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "results": tracks,
    })


# ── Genres / Stats ────────────────────────────────────────────────────────────

@app.get("/api/genres")
def api_genres():
    return jsonify(db.get_genres())


@app.get("/api/stats")
def api_stats():
    stats = db.get_stats()
    sc = scanner.status()
    stats["last_scan"] = sc.get("finished_at")
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
        from PIL import Image
        import io as _io
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

    range_header = request.headers.get("Range")
    size = os.path.getsize(path)
    mime = _guess_mime(path)

    if range_header:
        byte1, byte2 = _parse_range(range_header, size)
        if byte1 is None:
            return "", 416  # Range Not Satisfiable
        length = byte2 - byte1 + 1

        def generate():
            with open(path, "rb") as f:
                f.seek(byte1)
                remaining = length
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        from flask import Response
        headers = {
            "Content-Range": f"bytes {byte1}-{byte2}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": length,
            "Content-Type": mime,
        }
        return Response(generate(), 206, headers=headers)

    return send_file(path, mimetype=mime, conditional=True)


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
    if not g.user or not g.user.get("allow_download"):
        return jsonify({"error": "Download nicht erlaubt."}), 403
    import zipfile, io, time
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

    # Always record per-user play count
    db.increment_user_play_count(user["id"], track_id)

    # Only admin writes to the global counter and file tag
    if user["role"] == "admin":
        new_count, raw_path = db.increment_play_count(track_id)
        if raw_path is None:
            abort(404)
        path = _safe_path(raw_path)
        if path and os.path.isfile(path):
            tag_count = _read_play_count_tag(path)
            new_count = max(tag_count, new_count - 1) + 1
            db.set_play_count(track_id, new_count)
            _write_play_count_tag(path, new_count)
    else:
        # Verify track exists
        with db.db() as conn:
            if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (track_id,)).fetchone():
                abort(404)
        new_count = None

    return jsonify({"ok": True, "play_count": new_count})


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
            tags = ID3(path)
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
    except Exception as e:
        logging.getLogger(__name__).warning("Could not write play count tag to %s: %s", path, e)


# ── Radio / Random ────────────────────────────────────────────────────────────

@app.get("/api/random")
def api_random():
    _touch_disco()
    count   = min(int(request.args.get("count", 25)), 100)
    exclude = [int(x) for x in request.args.getlist("exclude") if x.isdigit()]
    return jsonify(db.get_random_tracks(count, exclude))


# ── Last.fm ───────────────────────────────────────────────────────────────────

def _require_admin_or_401():
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    if g.user["role"] != "admin":
        return jsonify({"error": "forbidden"}), 403
    return None

@app.get("/api/lastfm/status")
def api_lastfm_status():
    sk       = db.get_setting("lastfm_session_key")
    username = db.get_setting("lastfm_username")
    return jsonify({"connected": bool(sk), "username": username})


@app.get("/api/lastfm/auth")
def api_lastfm_auth():
    err = _require_admin_or_401()
    if err: return err
    callback = request.host_url.rstrip("/") + "/api/lastfm/callback"
    url = lastfm.get_auth_url(callback)
    return redirect(url)


@app.get("/api/lastfm/callback")
def api_lastfm_callback():
    token = request.args.get("token")
    if not token:
        return "Kein Token erhalten.", 400
    try:
        session = lastfm.get_session(token)
        db.set_setting("lastfm_session_key", session["key"])
        db.set_setting("lastfm_username",    session["name"])
    except Exception as e:
        return f"Last.fm Auth fehlgeschlagen: {html.escape(str(e))}", 500

    username = html.escape(db.get_setting("lastfm_username") or "")
    return f"""<html><body style="font-family:sans-serif;padding:40px;background:#30302E;color:#ECECEC">
        <h2 style="color:#7F77DD">&#10003; Last.fm verbunden!</h2>
        <p>Du bist als <strong>{username}</strong> eingeloggt.</p>
        <p><a href="/" style="color:#7F77DD">Zur&#252;ck zur App</a></p>
    </body></html>"""


@app.post("/api/lastfm/disconnect")
def api_lastfm_disconnect():
    err = _require_admin_or_401()
    if err: return err
    db.del_setting("lastfm_session_key")
    db.del_setting("lastfm_username")
    return jsonify({"ok": True})


_lastfm_loved_sync = {"running": False, "error": None, "count": 0, "finished_at": None}
_lastfm_pc_sync    = {"running": False, "error": None, "done": 0, "total": 0, "finished_at": None}


def _sync_lastfm_loved_tracks():
    global _lastfm_loved_sync
    username = db.get_setting("lastfm_username")
    if not username:
        _lastfm_loved_sync.update(running=False, error="not connected")
        return
    try:
        items = lastfm.get_loved_tracks(username)
        count = db.replace_lastfm_loved_tracks(items)

        # Write LOVE RATING tag to files that don't have it yet
        tagged = 0
        for track in db.get_loved_tracks_for_tag_write():
            try:
                scanner.write_love_tag(track["path"], True)
                tagged += 1
            except Exception:
                logging.getLogger(__name__).warning("Could not write love tag to %s", track["path"])

        _lastfm_loved_sync.update(running=False, error=None, count=count,
                                  tagged=tagged, finished_at=_time.time())
    except Exception as e:
        logging.getLogger(__name__).exception("Last.fm loved sync failed")
        _lastfm_loved_sync.update(running=False, error=str(e), finished_at=_time.time())


@app.get("/api/lastfm/loved/status")
def api_lastfm_loved_status():
    status = db.get_lastfm_loved_status()
    status.update(_lastfm_loved_sync)
    status["connected"] = bool(db.get_setting("lastfm_session_key"))
    return jsonify(status)


@app.post("/api/lastfm/loved/sync")
def api_lastfm_loved_sync():
    err = _require_admin_or_401()
    if err: return err
    if not db.get_setting("lastfm_session_key"):
        return jsonify({"error": "not connected"}), 401
    _lastfm_loved_sync.update(running=True, error=None)
    _sync_lastfm_loved_tracks()
    status = db.get_lastfm_loved_status()
    status.update(_lastfm_loved_sync)
    return jsonify(status)


def _sync_lastfm_playcounts():
    global _lastfm_pc_sync
    username = db.get_setting("lastfm_username")
    sk       = db.get_setting("lastfm_session_key")
    if not username or not sk:
        _lastfm_pc_sync.update(running=False, error="not connected")
        return
    log = logging.getLogger(__name__)
    try:
        with db.db() as conn:
            tracks = conn.execute(
                "SELECT id, path, artist, title FROM tracks WHERE artist IS NOT NULL AND title IS NOT NULL"
            ).fetchall()
        total = len(tracks)
        _lastfm_pc_sync.update(total=total, done=0)
        updated = 0
        for i, row in enumerate(tracks):
            _lastfm_pc_sync["done"] = i + 1
            try:
                pc = lastfm.get_user_track_playcount(username, row["artist"], row["title"])
                if pc and pc > 0:
                    # Update user_play_counts for admin (user_id=1), only if Last.fm count is higher
                    with db.db() as conn:
                        conn.execute("""
                            INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
                            VALUES (1, ?, ?, NULL)
                            ON CONFLICT(user_id, track_id) DO UPDATE SET
                                count = MAX(count, excluded.count)
                        """, (row["id"], pc))
                    # Write PCNT tag to file
                    path = _safe_path(row["path"])
                    if path and os.path.isfile(path):
                        try:
                            _write_play_count_tag(path, pc)
                        except Exception:
                            log.debug("Could not write play count tag to %s", path)
                    updated += 1
            except Exception:
                log.debug("Playcount sync failed for %s - %s", row["artist"], row["title"])
        _lastfm_pc_sync.update(running=False, error=None, done=total,
                               updated=updated, finished_at=_time.time())
    except Exception as e:
        log.exception("Last.fm playcount sync failed")
        _lastfm_pc_sync.update(running=False, error=str(e), finished_at=_time.time())


@app.get("/api/lastfm/playcount/status")
def api_lastfm_pc_status():
    err = _require_admin_or_401()
    if err: return err
    return jsonify(_lastfm_pc_sync)


@app.post("/api/lastfm/playcount/sync")
def api_lastfm_pc_sync():
    err = _require_admin_or_401()
    if err: return err
    if not db.get_setting("lastfm_session_key"):
        return jsonify({"error": "not connected"}), 401
    if _lastfm_pc_sync.get("running"):
        return jsonify({"error": "already running"}), 409
    _lastfm_pc_sync.update(running=True, error=None, done=0, total=0)
    import threading
    threading.Thread(target=_sync_lastfm_playcounts, daemon=True).start()
    return jsonify({"ok": True, "message": "sync started"})


@app.post("/api/lastfm/nowplaying")
def api_lastfm_nowplaying():
    sk = db.get_setting("lastfm_session_key")
    if not sk:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    try:
        lastfm.now_playing(sk, artist, title, duration=body.get("duration"))
        return jsonify({"ok": True})
    except Exception:
        logging.getLogger(__name__).exception("Last.fm now_playing failed")
        return jsonify({"error": "Last.fm request failed"}), 500


@app.post("/api/lastfm/scrobble")
def api_lastfm_scrobble():
    sk = db.get_setting("lastfm_session_key")
    if not sk:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    try:
        lastfm.scrobble(sk, artist, title)
        return jsonify({"ok": True})
    except Exception:
        logging.getLogger(__name__).exception("Last.fm scrobble failed")
        return jsonify({"error": "Last.fm request failed"}), 500


@app.post("/api/lastfm/love")
def api_lastfm_love():
    err = _require_admin_or_401()
    if err: return err
    sk = db.get_setting("lastfm_session_key")
    if not sk:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    action = body.get("action", "love")
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    try:
        if action == "love":
            lastfm.love(sk, artist, title)
            db.set_lastfm_loved(artist, title, True)
        else:
            lastfm.unlove(sk, artist, title)
            db.set_lastfm_loved(artist, title, False)
        return jsonify({"ok": True, "loved": action == "love"})
    except Exception:
        logging.getLogger(__name__).exception("Last.fm love/unlove failed")
        return jsonify({"error": "Last.fm request failed"}), 500


@app.get("/api/lastfm/loved")
def api_lastfm_loved():
    sk = db.get_setting("lastfm_session_key")
    if not sk:
        return jsonify({"loved": False})
    artist = request.args.get("artist", "")
    title  = request.args.get("title", "")
    try:
        info = lastfm.get_track_info(sk, artist, title)
        loved = str(info.get("userloved", "0")) == "1"
        return jsonify({"loved": loved})
    except Exception:
        return jsonify({"loved": False})


# ── Scanner ───────────────────────────────────────────────────────────────────

@app.post("/api/scan/start")
def api_scan_start():
    if not os.path.isdir(MUSIC_ROOT):
        return jsonify({"error": f"MUSIC_ROOT not found: {MUSIC_ROOT}"}), 400
    scanner.run_scan(MUSIC_ROOT)
    return jsonify({"status": "started"})


@app.post("/api/scan/bpm-tags")
def api_bpm_tags():
    """Read BPM from file tags (TBPM etc.) and update DB — fast, no audio analysis."""
    import threading
    def _worker():
        updated = 0
        try:
            from db import get_connection
            conn = get_connection()
            rows = conn.execute("SELECT id, path FROM tracks").fetchall()
            conn.close()
            for row in rows:
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
            import logging; logging.getLogger(__name__).error("bpm-tags: %s", e)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return jsonify({"status": "started", "updated": 0, "note": "running in background"})


@app.post("/api/scan/bpm")
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
    s.update(db.get_scanner_status())
    return jsonify(s)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

db.init_db()
_auth.load_persisted_blocks()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
