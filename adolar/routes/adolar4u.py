"""Adolar4U personalization and learning-journal routes."""

from flask import Blueprint, abort, g, jsonify, request, send_file

from .. import adolar4u, db, errors
from .. import auth as _auth
from ..application import APP_VERSION, _client_error, _int_arg

blueprint = Blueprint("adolar4u", __name__)

# ── Adolar4U optional personalization module ─────────────────────────────────

@blueprint.get("/api/adolar4u/status")
@_auth.login_required
def api_adolar4u_status():
    global_settings = adolar4u.get_global_settings()
    user_settings = adolar4u.get_user_settings(g.user["id"])
    response = jsonify({
        "global": global_settings,
        "user": user_settings,
        "onboarding": adolar4u.get_onboarding_state(g.user["id"]),
        "collecting": bool(
            global_settings["enabled"]
            and user_settings["enabled"]
            and not user_settings["learning_paused"]
        ),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.get("/api/adolar4u/onboarding/options")
@_auth.login_required
def api_adolar4u_onboarding_options():
    kind = str(request.args.get("kind") or "").strip().lower()
    try:
        options = adolar4u.search_onboarding_options(
            kind, request.args.get("q", ""), _int_arg("limit", 12, 1, 30),
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except ValueError as exc:
        return _client_error("Ungültige Onboarding-Anfrage.", exc)
    return jsonify(options)


@blueprint.post("/api/adolar4u/onboarding")
@_auth.login_required
def api_adolar4u_onboarding_complete():
    data = request.get_json(silent=True) or {}
    try:
        onboarding = adolar4u.complete_onboarding(
            g.user["id"], data.get("artists"), data.get("genres"),
        )
        # 5 to play immediately + one background-refill batch worth (see
        # RADIO_REFILL_BATCH in static/js/app.js) — matches startRadio()'s
        # normal fetch shape instead of over-committing to a stale snapshot.
        initial_playlist = adolar4u.recommend_tracks(g.user["id"], count=10) or []
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except ValueError as exc:
        return _client_error("Ungültige Onboarding-Auswahl.", exc)
    return jsonify({
        "onboarding": onboarding,
        "initial_playlist": initial_playlist,
    }), 201


@blueprint.put("/api/adolar4u/settings")
@_auth.login_required
def api_adolar4u_user_settings_put():
    data = request.get_json(silent=True) or {}
    allowed = {"enabled", "learning_paused", "collaborative_enabled", "discovery_level"}
    boolean_fields = {"enabled", "learning_paused", "collaborative_enabled"}
    if any(key not in allowed for key in data):
        return jsonify({"error": "unknown setting"}), 400
    if any(key in data and not isinstance(data[key], bool) for key in boolean_fields):
        return jsonify({"error": "settings must be boolean"}), 400
    try:
        settings = adolar4u.update_user_settings(g.user["id"], data)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except ValueError as exc:
        return _client_error("Ungültige Adolar4U-Einstellungen.", exc)
    return jsonify(settings)


@blueprint.delete("/api/adolar4u/profile")
@_auth.login_required
def api_adolar4u_profile_delete():
    deleted = adolar4u.delete_profile(g.user["id"])
    return jsonify({"ok": True, "deleted_events": deleted})


@blueprint.post("/api/adolar4u/events/<int:track_id>")
@_auth.login_required
def api_adolar4u_event(track_id):
    try:
        result = adolar4u.record_event(
            g.user["id"], track_id, request.get_json(silent=True) or {},
        )
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    except ValueError as exc:
        return _client_error("Ungültiges Hörereignis.", exc)
    except LookupError:
        abort(404)
    return jsonify(result), 202 if result.get("accepted") else 200


@blueprint.get("/api/adolar4u/history")
@_auth.login_required
def api_adolar4u_history():
    days = _int_arg("days", 7, min_val=1, max_val=60)
    limit = _int_arg("limit", 100, min_val=1, max_val=200)
    return jsonify(adolar4u.get_learning_history(g.user["id"], days, limit))


@blueprint.get("/api/adolar4u/history/export")
@_auth.login_required
def api_adolar4u_history_export():
    days = _int_arg("days", 60, min_val=1, max_val=60)
    archive, filename = adolar4u.build_learning_export(
        g.user["id"], days, APP_VERSION,
    )
    response = send_file(
        archive, mimetype="application/zip", as_attachment=True,
        download_name=filename,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.get("/api/admin/adolar4u/settings")
@_auth.admin_required
def api_adolar4u_admin_settings_get():
    return jsonify(adolar4u.get_global_settings())


@blueprint.put("/api/admin/adolar4u/settings")
@_auth.admin_required
def api_adolar4u_admin_settings_put():
    data = request.get_json(silent=True) or {}
    allowed = {"enabled", "audio_analysis", "collaborative"}
    if any(key not in allowed for key in data):
        return jsonify({"error": "unknown setting"}), 400
    if any(not isinstance(value, bool) for value in data.values()):
        return jsonify({"error": "settings must be boolean"}), 400
    settings = adolar4u.update_global_settings(data)
    db.log_audit(g.user["id"], "adolar4u.settings_updated", "system")
    return jsonify(settings)
