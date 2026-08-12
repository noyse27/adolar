"""Personal Last.fm connection, synchronization, and scrobbling routes."""

import html
import logging
import time as _time

from flask import Blueprint, g, jsonify, redirect, request
from flask import session as flask_session

from .. import auth as _auth
from .. import db, lastfm
from ..application import _start_library_thread, _submit_lastfm_call

blueprint = Blueprint("lastfm", __name__)

# ── Last.fm ───────────────────────────────────────────────────────────────────

def _lastfm_account():
    return db.get_lastfm_account(g.user["id"]) if g.user else None


def _lastfm_sync_state(user_id: int, job_type: str) -> dict:
    return db.get_lastfm_sync_state(user_id, job_type)


def _update_lastfm_sync_state(user_id: int, job_type: str, **values) -> dict:
    if "count" in values:
        values["result_count"] = values.pop("count")
    if "updated" in values:
        values["updated_count"] = values.pop("updated")
    return db.update_lastfm_sync_state(user_id, job_type, **values)

@blueprint.get("/api/lastfm/status")
def api_lastfm_status():
    account = _lastfm_account()
    return jsonify({
        "connected": bool(account),
        "username": account["username"] if account else None,
        "auto_love_favorites": bool(account and account["auto_love_favorites"]),
    })


@blueprint.get("/api/lastfm/auth")
def api_lastfm_auth():
    flask_session["lastfm_auth_user_id"] = g.user["id"]
    callback = request.host_url.rstrip("/") + "/api/lastfm/callback"
    url = lastfm.get_auth_url(callback)
    return redirect(url)


@blueprint.get("/api/lastfm/callback")
def api_lastfm_callback():
    pending_user_id = flask_session.pop("lastfm_auth_user_id", None)
    if not g.user or pending_user_id != g.user["id"]:
        return "Last.fm Auth-Sitzung ist abgelaufen. Bitte erneut verbinden.", 400
    token = request.args.get("token")
    if not token:
        return "Kein Token erhalten.", 400
    try:
        session = lastfm.get_session(token)
        db.set_lastfm_account(g.user["id"], session["name"], session["key"])
    except Exception as e:
        logging.getLogger(__name__).warning("Last.fm Auth fehlgeschlagen (%s)", e)
        return "Last.fm Auth fehlgeschlagen. Bitte erneut verbinden.", 500

    username = html.escape(session.get("name") or "")
    return f"""<html><body style="font-family:sans-serif;padding:40px;background:#30302E;color:#ECECEC">
        <h2 style="color:#7F77DD">&#10003; Last.fm verbunden!</h2>
        <p>Du bist als <strong>{username}</strong> eingeloggt.</p>
        <p><a href="/" style="color:#7F77DD">Zur&#252;ck zur App</a></p>
    </body></html>"""


@blueprint.post("/api/lastfm/disconnect")
def api_lastfm_disconnect():
    db.disconnect_lastfm_account(g.user["id"])
    return jsonify({"ok": True})


def _sync_lastfm_loved_tracks(user_id: int):
    account = db.get_lastfm_account(user_id)
    if not account:
        _update_lastfm_sync_state(user_id, "loved", running=False, error="not connected")
        return
    try:
        items = lastfm.get_loved_tracks(account["username"])
        count = db.replace_lastfm_loved_tracks(user_id, items)
        _update_lastfm_sync_state(
            user_id, "loved", running=False, error=None, count=count,
            finished_at=_time.time(),
        )
    except Exception as e:
        logging.getLogger(__name__).exception("Last.fm loved sync failed")
        _update_lastfm_sync_state(
            user_id, "loved", running=False, error=str(e), finished_at=_time.time(),
        )


@blueprint.get("/api/lastfm/loved/status")
def api_lastfm_loved_status():
    status = db.get_lastfm_loved_status(g.user["id"])
    status.update(_lastfm_sync_state(g.user["id"], "loved"))
    status["connected"] = bool(_lastfm_account())
    return jsonify(status)


@blueprint.post("/api/lastfm/loved/sync")
def api_lastfm_loved_sync():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    if not db.claim_lastfm_sync_job(g.user["id"], "loved"):
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_sync_lastfm_loved_tracks, args=(g.user["id"],))
    return jsonify({"ok": True, "message": "sync started"}), 202


def _sync_lastfm_playcounts(user_id: int):
    account = db.get_lastfm_account(user_id)
    if not account:
        _update_lastfm_sync_state(user_id, "playcounts", running=False, error="not connected")
        return
    log = logging.getLogger(__name__)
    try:
        user = _auth.get_user_by_id(user_id)
        contributes_archive = bool(
            user and (user.get("role") == "admin" or user.get("contributes_playcount"))
        )
        with db.db() as conn:
            tracks = conn.execute(
                "SELECT id, path, artist, title FROM tracks WHERE artist IS NOT NULL AND title IS NOT NULL"
            ).fetchall()
        total = len(tracks)
        _update_lastfm_sync_state(user_id, "playcounts", total=total, done=0)
        updated = 0
        for i, row in enumerate(tracks):
            if i == 0 or (i + 1) % 25 == 0 or i + 1 == total:
                _update_lastfm_sync_state(user_id, "playcounts", done=i + 1)
            try:
                pc = lastfm.get_user_track_playcount(
                    account["username"], row["artist"], row["title"]
                )
                if pc and pc > 0:
                    # Last.fm may raise personal and archive counts, never lower either.
                    with db.db() as conn:
                        conn.execute("""
                            INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
                            VALUES (?, ?, ?, NULL)
                            ON CONFLICT(user_id, track_id) DO UPDATE SET
                                count = MAX(count, excluded.count)
                        """, (user_id, row["id"], pc))
                    if contributes_archive and db.merge_archive_play_count(row["id"], pc):
                        updated += 1
            except Exception:
                log.debug("Playcount sync failed for %s - %s", row["artist"], row["title"])
        _update_lastfm_sync_state(
            user_id, "playcounts", running=False, error=None, done=total,
            updated=updated, finished_at=_time.time(),
        )
        with db.db() as conn:
            conn.execute(
                "UPDATE user_lastfm_accounts SET playcounts_synced_at=? WHERE user_id=?",
                (_time.time(), int(user_id)),
            )
    except Exception as e:
        log.exception("Last.fm playcount sync failed")
        _update_lastfm_sync_state(
            user_id, "playcounts", running=False, error=str(e),
            finished_at=_time.time(),
        )


@blueprint.get("/api/lastfm/playcount/status")
def api_lastfm_pc_status():
    return jsonify(_lastfm_sync_state(g.user["id"], "playcounts"))


@blueprint.post("/api/lastfm/playcount/sync")
def api_lastfm_pc_sync():
    if not _lastfm_account():
        return jsonify({"error": "not connected"}), 401
    if not db.claim_lastfm_sync_job(g.user["id"], "playcounts"):
        return jsonify({"error": "already running"}), 409
    _start_library_thread(_sync_lastfm_playcounts, args=(g.user["id"],))
    return jsonify({"ok": True, "message": "sync started"})


@blueprint.post("/api/lastfm/nowplaying")
def api_lastfm_nowplaying():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    queued = _submit_lastfm_call(
        "now_playing", lastfm.now_playing,
        account["session_key"], artist, title, duration=body.get("duration"),
    )
    return jsonify({"ok": True, "queued": queued}), 202


@blueprint.post("/api/lastfm/scrobble")
def api_lastfm_scrobble():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    queued = _submit_lastfm_call(
        "scrobble", lastfm.scrobble, account["session_key"], artist, title,
        retries=1,
    )
    return jsonify({"ok": True, "queued": queued}), 202


@blueprint.post("/api/lastfm/love")
def api_lastfm_love():
    account = _lastfm_account()
    if not account:
        return jsonify({"error": "not connected"}), 401
    body   = request.json or {}
    action = body.get("action", "love")
    artist = body.get("artist", "")
    title  = body.get("title", "")
    if not artist or not title:
        return jsonify({"error": "missing artist/title"}), 400
    try:
        if action == "love":
            lastfm.love(account["session_key"], artist, title)
            db.set_lastfm_loved(g.user["id"], artist, title, True)
        else:
            lastfm.unlove(account["session_key"], artist, title)
            db.set_lastfm_loved(g.user["id"], artist, title, False)
        return jsonify({"ok": True, "loved": action == "love"})
    except Exception:
        logging.getLogger(__name__).exception("Last.fm love/unlove failed")
        return jsonify({"error": "Last.fm request failed"}), 500


@blueprint.get("/api/lastfm/loved")
def api_lastfm_loved():
    account = _lastfm_account()
    if not account:
        return jsonify({"loved": False})
    artist = request.args.get("artist", "")
    title  = request.args.get("title", "")
    try:
        info = lastfm.get_track_info(account["session_key"], artist, title)
        loved = str(info.get("userloved", "0")) == "1"
        return jsonify({"loved": loved})
    except Exception:
        return jsonify({"loved": False})


@blueprint.patch("/api/lastfm/settings")
def api_lastfm_settings():
    data = request.get_json(silent=True) or {}
    if set(data) - {"auto_love_favorites"}:
        return jsonify({"error": "invalid setting"}), 400
    enabled = data.get("auto_love_favorites")
    if not isinstance(enabled, bool):
        return jsonify({"error": "auto_love_favorites must be boolean"}), 400
    if not db.set_lastfm_auto_love(g.user["id"], enabled):
        return jsonify({"error": "not connected"}), 404
    return jsonify({"ok": True, "auto_love_favorites": enabled})
