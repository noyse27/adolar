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

from flask import Blueprint, g, jsonify, request

from .. import auth as _auth
from .. import db, songster

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
