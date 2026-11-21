"""Personal Adolar Scrobbler connection and scrobbling routes.

Mirrors routes/lastfm.py closely - same shape, same background-call queue -
but login happens via username+password (auth.getMobileSession) instead of
Last.fm's browser-redirect auth.getSession flow.
"""

import logging
import time

from flask import Blueprint, g, jsonify, request

from .. import adolar_scrobbler, db
from ..application import _start_library_thread, _submit_lastfm_call

blueprint = Blueprint("adolar_scrobbler", __name__)


def _account():
    return db.get_adolar_scrobbler_account(g.user["id"]) if g.user else None


@blueprint.get("/api/adolar-scrobbler/status")
def api_adolar_scrobbler_status():
    account = _account()
    if account:
        db.get_or_create_lastfm_loved_radio_station(g.user["id"], "adolar_scrobbler")
    return jsonify({
        "configured": adolar_scrobbler.configured(),
        "connected": bool(account),
        "username": account["username"] if account else None,
        "auto_love_favorites": bool(account and account["auto_love_favorites"]),
    })


@blueprint.post("/api/adolar-scrobbler/connect")
def api_adolar_scrobbler_connect():
    if not adolar_scrobbler.configured():
        return jsonify({"error": "not_configured"}), 400
    body = request.json or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"error": "missing_credentials"}), 400
    try:
        session = adolar_scrobbler.get_mobile_session(username, password)
        if not session.get("key"):
            return jsonify({"error": "invalid_credentials"}), 401
        # Only one scrobble destination is active at a time - no parallel
        # operation. See adolar/routes/lastfm.py's callback for the mirror.
        db.disconnect_lastfm_account(g.user["id"])
        db.set_adolar_scrobbler_account(g.user["id"], session["name"], session["key"])
        db.get_or_create_lastfm_loved_radio_station(g.user["id"], "adolar_scrobbler")
        if db.claim_lastfm_sync_job(g.user["id"], "loved"):
            _start_library_thread(_sync_loved_tracks, args=(g.user["id"],))
        return jsonify({"ok": True, "username": session["name"]})
    except Exception as e:
        logging.getLogger(__name__).warning("Adolar Scrobbler Login fehlgeschlagen (%s)", e)
        return jsonify({"error": "login_failed"}), 502


@blueprint.post("/api/adolar-scrobbler/disconnect")
def api_adolar_scrobbler_disconnect():
    db.disconnect_adolar_scrobbler_account(g.user["id"])
    return jsonify({"ok": True})


def _sync_loved_tracks(user_id: int):
    account = db.get_adolar_scrobbler_account(user_id)
    if not account:
        db.update_lastfm_sync_state(user_id, "loved", running=False, error="not connected")
        return
    try:
        items = adolar_scrobbler.get_loved_tracks(account["username"])
        count = db.replace_lastfm_loved_tracks(user_id, items, "adolar_scrobbler")
        db.get_or_create_lastfm_loved_radio_station(user_id, "adolar_scrobbler")
        db.update_lastfm_sync_state(
            user_id, "loved", running=False, error=None, result_count=count,
            finished_at=time.time(),
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Adolar Scrobbler loved sync failed")
        db.update_lastfm_sync_state(
            user_id, "loved", running=False, error=str(exc), finished_at=time.time(),
        )


@blueprint.get("/api/adolar-scrobbler/loved/status")
def api_adolar_scrobbler_loved_status():
    status = db.get_lastfm_loved_status(g.user["id"])
    status.update(db.get_lastfm_sync_state(g.user["id"], "loved"))
    status["connected"] = bool(_account())
    return jsonify(status)


@blueprint.post("/api/adolar-scrobbler/loved/sync")
def api_adolar_scrobbler_loved_sync():
    if not _account():
        return jsonify({"error": "not connected"}), 401
    if not db.claim_lastfm_sync_job(g.user["id"], "loved"):
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_sync_loved_tracks, args=(g.user["id"],))
    return jsonify({"ok": True, "message": "sync started"}), 202


@blueprint.post("/api/adolar-scrobbler/nowplaying")
def api_adolar_scrobbler_nowplaying():
    account = _account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    metadata = {key: body[key] for key in ("album", "year") if body.get(key)}
    if body.get("duration"):
        metadata["duration"] = body["duration"]
    queued = _submit_lastfm_call(
        "adolar_scrobbler now_playing", adolar_scrobbler.now_playing,
        account["session_key"], artist, title, **metadata,
    )
    return jsonify({"ok": True, "queued": queued}), 202


@blueprint.post("/api/adolar-scrobbler/scrobble")
def api_adolar_scrobbler_scrobble():
    account = _account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    metadata = {key: body[key] for key in ("album", "duration", "year") if body.get(key)}
    queued = _submit_lastfm_call(
        "adolar_scrobbler scrobble", adolar_scrobbler.scrobble,
        account["session_key"], artist, title, retries=1, **metadata,
    )
    return jsonify({"ok": True, "queued": queued}), 202


@blueprint.post("/api/adolar-scrobbler/love")
def api_adolar_scrobbler_love():
    account = _account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    action = body.get("action", "love")
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    func = adolar_scrobbler.love if action == "love" else adolar_scrobbler.unlove
    queued = _submit_lastfm_call(
        f"adolar_scrobbler {action}", func, account["session_key"], artist, title,
    )
    db.set_lastfm_loved(g.user["id"], artist, title, action == "love")
    return jsonify({"ok": True, "queued": queued}), 202


@blueprint.patch("/api/adolar-scrobbler/settings")
def api_adolar_scrobbler_settings():
    data = request.get_json(silent=True) or {}
    if set(data) - {"auto_love_favorites"}:
        return jsonify({"error": "invalid setting"}), 400
    enabled = data.get("auto_love_favorites")
    if not isinstance(enabled, bool):
        return jsonify({"error": "auto_love_favorites must be boolean"}), 400
    if not db.set_adolar_scrobbler_auto_love(g.user["id"], enabled):
        return jsonify({"error": "not connected"}), 404
    return jsonify({"ok": True, "auto_love_favorites": enabled})
