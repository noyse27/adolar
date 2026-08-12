"""HTML pages, library search, albums, genres, and status routes."""

import os

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_file

from .. import application as core
from .. import auth as _auth
from .. import db, scanner
from ..application import _disco_active, _int_arg, _touch_disco

blueprint = Blueprint("catalog", __name__)

# ── Pages ─────────────────────────────────────────────────────────────────────

@blueprint.route("/", methods=["HEAD"])
def index_head():
    return "", 200

@blueprint.get("/")
def index():
    if _auth.user_count() == 0:
        return redirect("/setup")
    return render_template("index.html", app_version=core.APP_VERSION)


@blueprint.get("/miniplayer")
def miniplayer():
    return render_template("miniplayer.html")


@blueprint.get("/hilfe/manual.html")
def manual():
    return send_file(os.path.join(core.PROJECT_ROOT, "hilfe", "manual.html"))


@blueprint.get("/radio")
def radio_companion():
    access = db.get_setting("companion_access", "public")
    if access == "disabled":
        abort(404)
    if access == "authenticated" and not g.user:
        return redirect("/login?next=/radio")
    return render_template("radio.html")


@blueprint.get("/radio/settings")
def radio_companion_settings():
    if not g.user or g.user.get("role") != "admin":
        abort(403)
    return render_template("radio_settings.html", app_version=core.APP_VERSION)


# ── Tracks ────────────────────────────────────────────────────────────────────

@blueprint.get("/api/search")
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


@blueprint.get("/api/albums")
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


@blueprint.get("/health")
def health():
    """Unauthenticated liveness probe for Docker/orchestration healthchecks."""
    return jsonify({"status": "ok"})


# ── Genres / Stats ────────────────────────────────────────────────────────────

@blueprint.get("/api/genres")
def api_genres():
    return jsonify(db.get_genres())


@blueprint.get("/api/stats")
def api_stats():
    stats = db.get_stats()
    sc = scanner.status()
    persisted_scan = db.get_scanner_status()
    stats["version"] = core.APP_VERSION
    stats["last_scan"] = sc.get("finished_at") or persisted_scan.get("finished_at")
    stats["disco_active"] = _disco_active()
    return jsonify(stats)


@blueprint.get("/api/disco-status")
def api_disco_status():
    """Lightweight endpoint polled by the UI to show Disco connection badge."""
    _touch_disco()  # also counts as a keepalive if Disco calls this
    return jsonify({
        "active": _disco_active(),
        "last_seen": core._disco_last_seen or None,
    })
