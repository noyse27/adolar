"""Random playback, smart shuffle, and radio-station routes."""

import contextlib
import hashlib
import json
import logging
import os
import time as _time

from flask import Blueprint, abort, g, jsonify, request, send_file
from werkzeug.utils import secure_filename

from .. import adolar4u, db, errors, smart_shuffle
from .. import application as core
from .. import auth as _auth
from ..application import _client_error, _int_arg, _safe_data_path, _touch_disco
from .media import guess_mime

blueprint = Blueprint("radio", __name__)

# ── Radio / Random ────────────────────────────────────────────────────────────

@blueprint.get("/api/random")
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


@blueprint.get("/api/shuffle")
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


@blueprint.get("/api/radio-stations")
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


@blueprint.post("/api/radio-stations")
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


@blueprint.put("/api/radio-stations/<int:station_id>")
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


@blueprint.delete("/api/radio-stations/<int:station_id>")
def api_radio_stations_delete(station_id):
    if not _auth.can(g.user, "create_radio_stations"):
        return jsonify({"error": "forbidden"}), 403
    if not db.delete_radio_station(station_id, g.user["id"], g.user["role"] == "admin"):
        return jsonify({"error": "not found or system station"}), 404
    return jsonify({"ok": True})


@blueprint.post("/api/radio-stations/test")
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


@blueprint.post("/api/radio-stations/<int:station_id>/jingle")
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
    os.makedirs(core.JINGLE_ROOT, exist_ok=True)
    target = os.path.join(core.JINGLE_ROOT, f"station_{station_id}{ext}")
    safe_target = _safe_data_path(target, core.JINGLE_ROOT)
    if safe_target is None:
        abort(400)
    for old_ext in (".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"):
        old = os.path.join(core.JINGLE_ROOT, f"station_{station_id}{old_ext}")
        if old != safe_target and os.path.exists(old):
            with contextlib.suppress(OSError):
                os.remove(old)
    file.save(safe_target)
    db.set_radio_station_jingle(station_id, safe_target, every, enabled)
    return jsonify(db.get_radio_station(station_id))


@blueprint.patch("/api/radio-stations/<int:station_id>/jingle")
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


@blueprint.delete("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_delete(station_id):
    err = _can_manage_station_or_404(station_id)
    if err: return err
    path = db.get_radio_station_jingle_path(station_id, enabled_only=False)
    db.set_radio_station_jingle(station_id, None, 0, False)
    if path:
        safe = _safe_data_path(path, core.JINGLE_ROOT)
        if safe and os.path.exists(safe):
            with contextlib.suppress(OSError):
                os.remove(safe)
    return jsonify(db.get_radio_station(station_id))


@blueprint.get("/api/radio-stations/<int:station_id>/jingle")
def api_radio_station_jingle_stream(station_id):
    path = db.get_radio_station_jingle_path(station_id)
    if not path:
        abort(404)
    safe = _safe_data_path(path, core.JINGLE_ROOT)
    if safe is None or not os.path.isfile(safe):
        abort(404)
    return send_file(safe, mimetype=guess_mime(safe), conditional=True)


@blueprint.get("/api/radio-stations/<int:station_id>/tracks")
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
