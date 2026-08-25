"""Favorites, playlists, and smart-rule editor routes."""

import json
from datetime import UTC

from flask import Blueprint, g, jsonify, request, send_file
from werkzeug.utils import secure_filename

from .. import auth as _auth
from .. import db, errors, favorites, smart_rules
from ..application import _client_error

blueprint = Blueprint("playlists", __name__)


@blueprint.get("/api/favorites")
def api_favorites_status():
    ids_raw = request.args.get("ids", "")
    track_ids = [int(value) for value in ids_raw.split(",") if value.strip().isdigit()]
    favorite_ids = db.get_favorite_track_ids(g.user["id"], track_ids or None)
    return jsonify({"track_ids": sorted(favorite_ids)})


@blueprint.put("/api/favorites/<int:track_id>")
def api_favorite_set(track_id):
    data = request.get_json(silent=True) or {}
    favorite = data.get("favorite")
    if not isinstance(favorite, bool):
        return jsonify({"error": "favorite must be boolean"}), 400
    result, status = favorites.set_user_favorite(g.user["id"], track_id, favorite)
    return jsonify(result), status


@blueprint.post("/api/radio/bookmark/<int:track_id>")
def api_radio_bookmark(track_id):
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user = _auth.get_user_by_token(token) if token else None
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    result, status = favorites.set_user_favorite(user["id"], track_id, True)
    if status == 200:
        result["playlist_id"] = db.get_or_create_favorites(user["id"])
    return jsonify(result), status


@blueprint.get("/api/playlists/memberships")
def api_playlist_memberships():
    if not g.user or not _auth.can(g.user, "create_playlists"):
        return jsonify({})
    ids_raw = request.args.get("ids", "")
    try:
        track_ids = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
    except ValueError:
        return jsonify({}), 400
    return jsonify(db.get_track_playlist_memberships(g.user["id"], track_ids))


@blueprint.post("/api/playlists/<int:playlist_id>/tracks")
def api_playlist_add_track(playlist_id):
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data     = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if not isinstance(track_id, int):
        return jsonify({"error": "track_id fehlt."}), 400
    with db.db() as conn:
        row = conn.execute(
            "SELECT id, type FROM playlists WHERE id=? AND owner_id=?",
            (playlist_id, g.user["id"])
        ).fetchone()
    if not row:
        return jsonify({"error": "Playlist nicht gefunden."}), 404
    if row["type"] != "static":
        return jsonify({"error": "Tracks können nur statischen Playlists hinzugefügt werden."}), 409
    db.add_track_to_playlist(playlist_id, track_id)
    return jsonify({"ok": True})


@blueprint.get("/api/playlists/<int:playlist_id>/tracks")
def api_playlist_tracks(playlist_id):
    tracks = db.get_playlist_tracks(playlist_id, g.user["id"] if g.user else 0)
    if tracks is None:
        return jsonify({"error": "Nicht gefunden."}), 404
    return jsonify(tracks)


@blueprint.get("/api/playlists")
def api_playlists_list():
    return jsonify(db.get_playlists(g.user["id"] if g.user else 0))


@blueprint.get("/api/playlist-editor/defaults")
def api_playlist_editor_defaults():
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"name": db.next_playlist_name(g.user["id"])})


@blueprint.post("/api/smart-rules/parse")
def api_smart_rules_parse():
    if not (_auth.can(g.user, "create_playlists") or
            _auth.can(g.user, "create_radio_stations")):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        parsed = smart_rules.parse_smart_rule(data.get("text"))
        parsed["filter"] = db.validate_radio_filter(parsed["filter"])
    except smart_rules.SmartRuleParseError as exc:
        return jsonify({"error": exc.user_message}), 400
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    return jsonify(parsed)


@blueprint.post("/api/playlist-editor/preview")
def api_playlist_editor_preview():
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        tracks = db.get_playlist_filter_tracks(
            data.get("filter") or {},
            user_id=g.user["id"],
            sort=data.get("sort") or "artist",
            limit=500,
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except ValueError as exc:
        return _client_error("Ungültige Filterparameter.", exc)
    return jsonify({"results": tracks, "total": len(tracks)})


@blueprint.post("/api/playlist-editor/fill")
def api_playlist_editor_fill():
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    try:
        count = max(1, min(int(data.get("count") or 50), 500))
        tracks = db.get_playlist_filter_tracks(
            data.get("filter") or {"editor_version": 1},
            user_id=g.user["id"],
            limit=count,
            random_order=True,
            exclude_ids=data.get("exclude_ids") or [],
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except (TypeError, ValueError) as exc:
        return _client_error("Ungültige Filterparameter.", exc)
    return jsonify({"results": tracks, "total": len(tracks)})


@blueprint.post("/api/playlist-editor/import")
def api_playlist_editor_import():
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    if data.get("format") != "adolar-disco-playlist" or data.get("version") != 1:
        return jsonify({"error": "Keine gültige Adolar-Playlist."}), 400
    wanted_tracks = data.get("tracks")
    if not isinstance(wanted_tracks, list) or len(wanted_tracks) > 5000:
        return jsonify({"error": "Ungültige oder zu große Trackliste."}), 400
    matched, unmatched = [], []
    with db.db() as conn:
        for wanted in wanted_tracks:
            if not isinstance(wanted, dict) or not str(wanted.get("title") or "").strip():
                return jsonify({"error": "Ein importierter Track hat keinen Titel."}), 400
            title = str(wanted.get("title") or "").strip()
            artist = str(wanted.get("artist") or "").strip()
            rows = conn.execute(
                """SELECT id, path, title, artist, album, genre, year, duration,
                          bitrate, cover_hash, bpm
                   FROM tracks
                   WHERE LOWER(TRIM(COALESCE(title,'')))=LOWER(TRIM(?))
                     AND (?='' OR LOWER(TRIM(COALESCE(artist,'')))=LOWER(TRIM(?)))
                   LIMIT 50""",
                (title, artist, artist),
            ).fetchall()
            if not rows:
                unmatched.append(wanted)
                continue
            wanted_album = str(wanted.get("album") or "").strip().casefold()
            try:
                wanted_duration = int(wanted.get("duration") or 0)
            except (TypeError, ValueError):
                wanted_duration = 0
            best = max(rows, key=lambda row: (
                20 if wanted_album and (row["album"] or "").strip().casefold() == wanted_album else 0,
                10 if wanted_duration and abs(int(row["duration"] or 0) - wanted_duration) <= 3 else 0,
            ))
            track = dict(best)
            track["has_cover"] = bool(track.get("cover_hash"))
            matched.append(track)
    return jsonify({
        "tracks": matched,
        "imported_count": len(wanted_tracks),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "unmatched": unmatched[:100],
    })


@blueprint.post("/api/playlist-editor/export")
def api_playlist_editor_export():
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("track_ids") or []
    try:
        track_ids = [int(value) for value in raw_ids][:5000]
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Trackliste."}), 400
    if not track_ids:
        return jsonify({"error": "Die Playlist ist leer."}), 400
    with db.db() as conn:
        placeholders = ",".join("?" * len(track_ids))
        rows = conn.execute(
            f"""SELECT id, title, artist, album, duration, year
                FROM tracks WHERE id IN ({placeholders})""",
            track_ids,
        ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in rows}
    import io
    from datetime import datetime
    payload = {
        "format": "adolar-disco-playlist",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "tracks": [
            {key: by_id[track_id].get(key)
             for key in ("title", "artist", "album", "duration", "year")}
            for track_id in track_ids if track_id in by_id
        ],
    }
    stream = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    safe_name = secure_filename(str(data.get("name") or "Adolar-Playlist")) or "Adolar-Playlist"
    return send_file(
        stream, mimetype="application/json", as_attachment=True,
        download_name=f"{safe_name}.adolarplaylist",
    )


@blueprint.post("/api/playlists")
def api_playlists_create():
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data    = request.get_json(silent=True) or {}
    name    = (data.get("name") or "").strip()
    type_   = data.get("type", "smart")
    filters = data.get("filters", {})
    sort    = data.get("sort", "artist")
    if not name:
        return jsonify({"error": "Name fehlt."}), 400
    try:
        pid = db.save_personal_playlist(
            g.user["id"], name, type_, json.dumps(filters), sort,
            data.get("track_ids") or [],
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except (TypeError, ValueError) as exc:
        return _client_error("Ungültige Playlist-Daten.", exc)
    return jsonify({"ok": True, "id": pid}), 201


@blueprint.put("/api/playlists/<int:playlist_id>")
def api_playlists_update(playlist_id):
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name fehlt."}), 400
    try:
        saved_id = db.save_personal_playlist(
            g.user["id"], name, data.get("type") or "static",
            json.dumps(data.get("filters") or {}),
            data.get("sort") or "artist", data.get("track_ids") or [],
            playlist_id=playlist_id,
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except (TypeError, ValueError) as exc:
        return _client_error("Ungültige Playlist-Daten.", exc)
    if saved_id is None:
        return jsonify({"error": "Nicht gefunden oder keine Berechtigung."}), 404
    return jsonify({"ok": True, "id": saved_id})

@blueprint.delete("/api/playlists/<int:playlist_id>")
def api_playlists_delete(playlist_id):
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    if not db.delete_playlist(playlist_id, g.user["id"]):
        return jsonify({"error": "Nicht gefunden oder keine Berechtigung."}), 404
    return jsonify({"ok": True})

@blueprint.patch("/api/playlists/<int:playlist_id>")
def api_playlists_rename(playlist_id):
    if not _auth.can(g.user, "create_playlists"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name fehlt."}), 400
    if not db.rename_playlist(playlist_id, g.user["id"], name):
        return jsonify({"error": "Nicht gefunden oder keine Berechtigung."}), 404
    return jsonify({"ok": True})
