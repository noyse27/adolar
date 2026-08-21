"""Adolar Songster integration routes.

Step 1 of the integration (see docs in the adolar-songster repo,
Adolar_Songster_Adolar_Integration_Konzept_v1_20260821.md): the global
enable/disable switch only. The actual /api/songster/login, playlists and
paginated-tracks endpoints for the game client are a later step.
"""

from flask import Blueprint, g, jsonify, request

from .. import auth as _auth
from .. import db, songster

blueprint = Blueprint("songster", __name__)


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
