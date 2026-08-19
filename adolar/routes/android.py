"""Adolar Mobile backend routes for Android background sync (Adolar Next)."""

from flask import Blueprint, g, jsonify, request

from .. import android, errors
from .. import auth as _auth
from ..application import _client_error

blueprint = Blueprint("android", __name__)


@blueprint.post("/api/android/v1/register-device")
@_auth.login_required
def api_android_register_device():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()[:120]
    token = _auth.create_android_device_token(g.user["id"], name)
    return jsonify({"device_token": token}), 201


@blueprint.delete("/api/android/v1/devices/<int:device_id>")
@_auth.login_required
def api_android_revoke_device(device_id):
    _auth.revoke_android_device_token(device_id, g.user["id"])
    return jsonify({"ok": True})


@blueprint.post("/api/android/v1/tracks/match")
@_auth.android_device_required
def api_android_match_tracks():
    data = request.get_json(silent=True) or {}
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return _client_error(
            "Feld 'tracks' muss eine Liste sein.", ValueError("tracks not a list"))
    try:
        results = android.match_tracks(g.user["id"], tracks)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    return jsonify({"results": results})


@blueprint.post("/api/android/v1/events/batch")
@_auth.android_device_required
def api_android_events_batch():
    data = request.get_json(silent=True) or {}
    events = data.get("events")
    if not isinstance(events, list):
        return _client_error(
            "Feld 'events' muss eine Liste sein.", ValueError("events not a list"))
    try:
        results = android.apply_event_batch(g.user, g.device["id"], events)
    except errors.ValidationError as exc:
        return _client_error(exc.user_message, exc)
    return jsonify({"results": results}), 202
