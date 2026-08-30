"""Adolar Songster integration routes.

Step 1 (see docs in the adolar-songster repo,
Adolar_Songster_Adolar_Integration_Konzept_v1_20260821.md): the global
enable/disable switch (api_songster_status, api_songster_admin_settings_*).

Step 2: the actual data-access surface used by the Songster game server at
table-creation time — GET /api/songster/playlists (which songster_enabled
stations are currently available) and GET /api/songster/playlists/<id>/tracks
(the full, paginated track pool for one of them; Songster's own batch
algorithm — year-spread, one-artist-per-batch, last_played_at malus — runs
client-side on this pool, not on Adolar).

Per INTEGRATION_STANDARDS.md section 3, server-to-server access uses the
existing Bearer API-token mechanism (adolar/auth.py, same as Taggster) rather
than a bespoke session-login endpoint: a Songster game server holds one
admin-issued token with product="songster" and sends it as
`Authorization: Bearer <token>` on every call. No browser session is
involved, so these routes are gated on g.token_product rather than
login_required/admin_required.
"""

import json

from flask import Blueprint, g, jsonify, request

from .. import auth as _auth
from .. import db, errors, songster
from ..application import _client_error

blueprint = Blueprint("songster", __name__)


def _songster_token_required(f):
    """Restrict a route to requests authenticated with a Bearer API token
    whose product is "songster", and only while the global Songster switch
    is enabled (see songster.get_global_settings). Session-cookie logins
    (regular Adolar Web users) are deliberately not accepted here — this
    surface is machine-to-machine only, matching Taggster's precedent."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None or getattr(g, "token_product", None) != "songster":
            return jsonify({"error": "unauthorized"}), 401
        if not songster.get_global_settings()["enabled"]:
            return jsonify({"error": "songster_disabled"}), 403
        return f(*args, **kwargs)

    return decorated


@blueprint.get("/api/songster/status")
@_auth.login_required
def api_songster_status():
    response = jsonify(songster.get_global_settings())
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.get("/api/admin/songster/settings")
@_auth.admin_required
def api_songster_admin_settings_get():
    return jsonify(songster.get_global_settings())


@blueprint.put("/api/admin/songster/settings")
@_auth.admin_required
def api_songster_admin_settings_put():
    data = request.get_json(silent=True) or {}
    allowed = {"enabled"}
    if any(key not in allowed for key in data):
        return jsonify({"error": "unknown setting"}), 400
    if any(not isinstance(value, bool) for value in data.values()):
        return jsonify({"error": "settings must be boolean"}), 400
    settings = songster.update_global_settings(data)
    db.log_audit(g.user["id"], "songster.settings_updated", "system")
    return jsonify(settings)


@blueprint.get("/api/songster/playlists")
@_songster_token_required
def api_songster_playlists():
    playlists = [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
        }
        for p in db.list_songster_playlists()
    ]
    return jsonify({"playlists": playlists})


@blueprint.get("/api/songster/playlists/<int:playlist_id>/tracks")
@_songster_token_required
def api_songster_playlist_tracks(playlist_id):
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400
    result = db.list_songster_playlist_tracks(playlist_id, limit=limit, offset=offset)
    if result is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(result)


# Audio playback (Step 4): the game server proxies this through to its own
# players rather than handing out this Bearer token, so it's fine for this
# to be a plain byte stream - same Range-aware streaming as the regular
# player's /api/stream/<id>, just gated behind the songster product token
# (and the global Songster switch) instead of being open to anyone on the
# network, see routes/media.py's stream_track_response docstring.
@blueprint.get("/api/songster/tracks/<int:track_id>/stream")
@_songster_token_required
def api_songster_track_stream(track_id):
    from .media import stream_track_response

    return stream_track_response(track_id)


# ── Step 3: admin management of Songster playlists (browser session, not
# Bearer token - this is the "Songster Playlists" dialog, reusing the radio
# station editor components minus jingle/scope, see concept doc section 3.3).


@blueprint.get("/api/admin/songster/playlists")
@_auth.admin_required
def api_admin_songster_playlists_list():
    return jsonify(db.list_songster_admin_playlists())


@blueprint.get("/api/admin/songster/tracks")
@_auth.admin_required
def api_admin_songster_tracks_lookup():
    ids_raw = request.args.get("ids", "")
    track_ids = [int(value) for value in ids_raw.split(",") if value.strip().isdigit()]
    return jsonify(db.list_songster_track_refs(track_ids))


@blueprint.post("/api/admin/songster/albums")
@_auth.admin_required
def api_admin_songster_albums_lookup():
    data = request.get_json(silent=True) or {}
    return jsonify(db.list_songster_album_refs(data.get("album_refs") or []))


@blueprint.post("/api/admin/songster/playlists/preview")
@_auth.admin_required
def api_admin_songster_playlists_preview():
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be integer"}), 400
    try:
        return jsonify(db.get_songster_playlist_preview(
            data.get("filter") or {},
            limit=limit,
            include_track_ids=data.get("include_track_ids") or [],
            exclude_track_ids=data.get("exclude_track_ids") or [],
            include_album_refs=data.get("include_album_refs") or [],
            exclude_album_refs=data.get("exclude_album_refs") or [],
        ))
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Playlist-Definition.", e)


@blueprint.post("/api/admin/songster/playlists/test")
@_auth.admin_required
def api_admin_songster_playlists_test():
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be integer"}), 400
    try:
        return jsonify(db.get_songster_playlist_test_tracks(
            data.get("filter") or {},
            limit=limit,
            include_track_ids=data.get("include_track_ids") or [],
            exclude_track_ids=data.get("exclude_track_ids") or [],
            include_album_refs=data.get("include_album_refs") or [],
            exclude_album_refs=data.get("exclude_album_refs") or [],
        ))
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Playlist-Definition.", e)


@blueprint.post("/api/admin/songster/playlists/<int:playlist_id>/queue")
@_auth.admin_required
def api_admin_songster_playlists_queue_add(playlist_id):
    data = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if not isinstance(track_id, int):
        return jsonify({"error": "track_id required"}), 400
    if not db.queue_songster_playlist_track(playlist_id, track_id, g.user["id"]):
        return jsonify({"error": "not_found"}), 404
    db.log_audit(g.user["id"], "songster.playlist_track_queued", str(playlist_id), str(track_id))
    return jsonify({"ok": True, "queue_count": db.get_songster_playlist_queue_count(playlist_id)})


@blueprint.get("/api/admin/songster/playlists/<int:playlist_id>/queue")
@_auth.admin_required
def api_admin_songster_playlists_queue_list(playlist_id):
    if not _songster_playlist_or_404(playlist_id):
        return jsonify({"error": "not_found"}), 404
    return jsonify({
        "tracks": db.list_songster_playlist_queue(playlist_id),
        "queue_count": db.get_songster_playlist_queue_count(playlist_id),
    })


@blueprint.post("/api/admin/songster/playlists/<int:playlist_id>/queue/sync")
@_auth.admin_required
def api_admin_songster_playlists_queue_sync(playlist_id):
    result = db.sync_songster_playlist_queue(playlist_id)
    if result is None:
        return jsonify({"error": "not_found"}), 404
    db.log_audit(g.user["id"], "songster.playlist_queue_synced", str(playlist_id), json.dumps({
        "accepted": len(result["accepted"]),
        "discarded": len(result["discarded"]),
    }))
    return jsonify(result)


@blueprint.post("/api/admin/songster/playlists")
@_auth.admin_required
def api_admin_songster_playlists_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        playlist_id = db.create_songster_playlist(
            name=name,
            description=data.get("description") or "",
            filter_def=data.get("filter") or {"mode": "all", "rules": []},
            user_id=g.user["id"],
        )
        db.set_songster_playlist_static_tracks(
            playlist_id,
            include_track_ids=data.get("include_track_ids") or [],
            exclude_track_ids=data.get("exclude_track_ids") or [],
        )
        db.set_songster_playlist_static_albums(
            playlist_id,
            include_album_refs=data.get("include_album_refs") or [],
            exclude_album_refs=data.get("exclude_album_refs") or [],
        )
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Playlist-Definition.", e)
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "name already exists"}), 409
        raise
    db.log_audit(g.user["id"], "songster.playlist_created", str(playlist_id), name)
    return jsonify(db.get_radio_station(playlist_id)), 201


def _songster_playlist_or_404(playlist_id: int) -> dict | None:
    station = db.get_radio_station(playlist_id)
    if not station or not station.get("songster_managed"):
        return None
    return station


@blueprint.put("/api/admin/songster/playlists/<int:playlist_id>")
@_auth.admin_required
def api_admin_songster_playlists_update(playlist_id):
    if not _songster_playlist_or_404(playlist_id):
        return jsonify({"error": "not_found"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        ok = db.update_radio_station(
            playlist_id,
            name=name,
            description=data.get("description") or "",
            filter_def=data.get("filter") or {"mode": "all", "rules": []},
            user_id=g.user["id"],
            is_admin=True,
        )
        if ok and ("include_track_ids" in data or "exclude_track_ids" in data):
            db.set_songster_playlist_static_tracks(
                playlist_id,
                include_track_ids=data.get("include_track_ids") or [],
                exclude_track_ids=data.get("exclude_track_ids") or [],
            )
        if ok and ("include_album_refs" in data or "exclude_album_refs" in data):
            db.set_songster_playlist_static_albums(
                playlist_id,
                include_album_refs=data.get("include_album_refs") or [],
                exclude_album_refs=data.get("exclude_album_refs") or [],
            )
    except errors.ValidationError as e:
        return _client_error(e.user_message, e)
    except ValueError as e:
        return _client_error("Ungültige Playlist-Definition.", e)
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "name already exists"}), 409
        raise
    if not ok:
        return jsonify({"error": "not_found"}), 404
    return jsonify(db.get_radio_station(playlist_id))


@blueprint.delete("/api/admin/songster/playlists/<int:playlist_id>")
@_auth.admin_required
def api_admin_songster_playlists_delete(playlist_id):
    if not _songster_playlist_or_404(playlist_id):
        return jsonify({"error": "not_found"}), 404
    db.delete_radio_station(playlist_id, g.user["id"], is_admin=True)
    db.log_audit(g.user["id"], "songster.playlist_deleted", str(playlist_id))
    return jsonify({"ok": True})


@blueprint.put("/api/admin/songster/playlists/<int:playlist_id>/enabled")
@_auth.admin_required
def api_admin_songster_playlists_set_enabled(playlist_id):
    data = request.get_json(silent=True) or {}
    if "enabled" not in data or not isinstance(data["enabled"], bool):
        return jsonify({"error": "enabled (boolean) required"}), 400
    if not db.set_songster_playlist_enabled(playlist_id, data["enabled"]):
        return jsonify({"error": "not_found"}), 404
    db.log_audit(
        g.user["id"],
        "songster.playlist_enabled" if data["enabled"] else "songster.playlist_disabled",
        str(playlist_id),
    )
    return jsonify(db.get_radio_station(playlist_id))
