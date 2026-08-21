"""Authentication, session, token, and user-management routes."""

import json
from urllib.parse import urlparse

from flask import Blueprint, g, jsonify, make_response, redirect, render_template, request

from .. import auth as _auth
from .. import db
from ..application import _safe_next_url

blueprint = Blueprint("auth", __name__)

# ── Auth routes ───────────────────────────────────────────────────────────────

@blueprint.get("/setup")
def setup_get():
    if _auth.user_count() > 0:
        return redirect("/login")
    return render_template("setup.html", error=None, username="")

@blueprint.post("/setup")
def setup_post():
    if _auth.user_count() > 0:
        return redirect("/")
    username  = request.form.get("username", "").strip()
    password  = request.form.get("password", "")
    password2 = request.form.get("password2", "")
    err = None
    if not username:
        err = "Benutzername darf nicht leer sein."
    elif len(password) < 8:
        err = "Passwort muss mindestens 8 Zeichen haben."
    elif password != password2:
        err = "Passwörter stimmen nicht überein."
    if err:
        return render_template("setup.html", error=err, username=username)
    user_id = _auth.create_user(username, password, role="admin")
    # Admin doesn't need to change password on first login
    with db.db() as conn:
        conn.execute("UPDATE users SET must_change_password=0 WHERE id=?", (user_id,))
    token = _auth.create_session(
        user_id, remember=False, product="adolar_web",
        ip_address=_auth._get_client_ip(),
    )
    resp = make_response(redirect("/"))
    resp.set_cookie(_auth.SESSION_COOKIE, token, httponly=True, samesite="Lax", max_age=_auth.SESSION_TTL)
    return resp


@blueprint.get("/login")
def login_get():
    if _auth.user_count() == 0:
        return redirect("/setup")
    ip = _auth._get_client_ip()
    blocked, secs = _auth._bf_check(ip)
    return render_template("login.html",
                           error=None, username="",
                           next=request.args.get("next", "/"),
                           blocked=blocked, blocked_seconds=secs)

@blueprint.post("/login")
def login_post():
    if _auth.user_count() == 0:
        return redirect("/setup")
    ip = _auth._get_client_ip()
    blocked, secs = _auth._bf_check(ip)
    if blocked:
        return render_template("login.html", error=None, username="",
                               next=request.form.get("next", "/"),
                               blocked=True, blocked_seconds=secs), 429

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    remember = bool(request.form.get("remember"))
    next_url = _safe_next_url(request.form.get("next"))

    user = _auth.get_user_by_name(username)
    if not user or not user.get("is_active", 1) or not _auth.verify_password(user, password):
        _auth._bf_record_failure(ip)
        blocked2, secs2 = _auth._bf_check(ip)
        err = "Ungültiger Benutzername oder Passwort."
        return render_template("login.html", error=err, username=username,
                               next=next_url, blocked=blocked2, blocked_seconds=secs2), 401

    _auth._bf_clear(ip)
    token = _auth.create_session(
        user["id"], remember, product="adolar_web", ip_address=ip,
    )
    max_age = _auth.SESSION_TTL_LONG if remember else _auth.SESSION_TTL
    # _safe_next_url already guarantees a same-origin path; this guard
    # restates the invariant in the exact form the CodeQL query help for
    # py/url-redirection documents as safe, so the analysis can verify it.
    if not urlparse(next_url).netloc and not urlparse(next_url).scheme:
        resp = make_response(redirect(next_url))
    else:
        resp = make_response(redirect("/"))
    resp.set_cookie(_auth.SESSION_COOKIE, token, httponly=True, samesite="Lax", max_age=max_age)
    return resp


@blueprint.post("/logout")
def logout():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    if token:
        _auth.delete_session(token)
    resp = make_response(redirect("/login"))
    resp.delete_cookie(_auth.SESSION_COOKIE)
    return resp


@blueprint.post("/api/radio/login")
def api_radio_login():
    if _auth.user_count() == 0:
        return jsonify({"error": "setup_required"}), 409
    ip = _auth._get_client_ip()
    blocked, secs = _auth._bf_check(ip)
    if blocked:
        return jsonify({"error": "blocked", "seconds": secs}), 429

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember", True))
    user = _auth.get_user_by_name(username)
    if not user or not user.get("is_active", 1) or not _auth.verify_password(user, password):
        _auth._bf_record_failure(ip)
        blocked2, secs2 = _auth._bf_check(ip)
        return jsonify({
            "error": "invalid_credentials",
            "blocked": blocked2,
            "seconds": secs2,
        }), 401
    if user["must_change_password"]:
        return jsonify({"error": "must_change_password"}), 403

    _auth._bf_clear(ip)
    product = str(request.headers.get("X-Adolar-Product", "companion")).lower()
    if product not in ("companion", "android"):
        product = "companion"
    token = _auth.create_session(
        user["id"], remember, product=product, ip_address=ip,
    )
    max_age = _auth.SESSION_TTL_LONG if remember else _auth.SESSION_TTL
    resp = jsonify({
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    })
    resp.set_cookie(_auth.SESSION_COOKIE, token, httponly=True, samesite="Lax", max_age=max_age)
    return resp


@blueprint.post("/api/radio/logout")
def api_radio_logout():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    if token:
        _auth.delete_session(token)
    resp = jsonify({"ok": True})
    resp.delete_cookie(_auth.SESSION_COOKIE)
    return resp


@blueprint.get("/change-password")
def change_password_get():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user = _auth.get_user_by_token(token) if token else None
    if not user:
        return redirect("/login")
    forced = bool(user["must_change_password"])
    return render_template("change_password.html", error=None, forced=forced)

@blueprint.post("/api/auth/change-password")
def api_change_password():
    token = request.cookies.get(_auth.SESSION_COOKIE)
    user = _auth.get_user_by_token(token) if token else None
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    data      = request.get_json(silent=True) or {}
    password  = data.get("password", "")
    password2 = data.get("password2", "")
    old_pw    = data.get("old_password", "")
    forced    = bool(user["must_change_password"])

    if not forced:
        full_user = _auth.get_user_by_name(user["username"])
        if not _auth.verify_password(full_user, old_pw):
            return jsonify({"error": "Aktuelles Passwort falsch."}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    if password != password2:
        return jsonify({"error": "Passwörter stimmen nicht überein."}), 400
    _auth.set_password(user["id"], password, must_change=False)
    return jsonify({"ok": True})


@blueprint.get("/api/me")
def api_me():
    if not g.user:
        return jsonify({"error": "unauthorized"}), 401
    is_admin = g.user["role"] == "admin"
    return jsonify({
        "id":             g.user["id"],
        "username":       g.user["username"],
        "role":           g.user["role"],
        "allow_download": is_admin or bool(g.user["allow_download"]),
        "allow_playlists": is_admin or _auth.can(g.user, "create_playlists"),
        "allow_radio_stations": is_admin or _auth.can(g.user, "create_radio_stations"),
        "allow_lyrics_edit": is_admin or _auth.can(g.user, "edit_lyrics"),
        "contributes_playcount": bool(g.user["contributes_playcount"]),
    })


# ── API tokens for admin tools (e.g. Adolar Taggster) ─────────────────────────
# Bearer-token auth, separate from the browser session cookie — see auth.py
# before_request(). The plaintext token is only ever returned by the create
# call; afterwards only id/name/timestamps are exposed.

@blueprint.get("/api/admin/tokens")
@_auth.admin_required
def api_tokens_list():
    return jsonify({"tokens": _auth.list_api_tokens(g.user["id"])})

@blueprint.post("/api/admin/tokens")
@_auth.admin_required
def api_tokens_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    product = (data.get("product") or "taggster").strip()
    token = _auth.create_api_token(g.user["id"], name, product)
    db.log_audit(g.user["id"], "api_token.created", details=json.dumps({"name": name, "product": product}))
    return jsonify({"token": token})

@blueprint.delete("/api/admin/tokens/<int:token_id>")
@_auth.admin_required
def api_tokens_revoke(token_id):
    _auth.revoke_api_token(token_id, g.user["id"])
    db.log_audit(g.user["id"], "api_token.revoked", target=str(token_id))
    return jsonify({"ok": True})


# ── User management (admin only) ──────────────────────────────────────────────

@blueprint.get("/api/users")
@_auth.admin_required
def api_users_list():
    return jsonify(_auth.get_all_users())

@blueprint.post("/api/users")
@_auth.admin_required
def api_users_create():
    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password", "")
    if not username:
        return jsonify({"error": "Benutzername fehlt."}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    if _auth.get_user_by_name(username):
        return jsonify({"error": "Benutzername bereits vergeben."}), 409
    uid = _auth.create_user(username, password, role="user")
    db.log_audit(g.user["id"], "user.created", f"user:{uid}", username)
    return jsonify({"ok": True, "id": uid}), 201

@blueprint.delete("/api/users/<int:user_id>")
@_auth.admin_required
def api_users_delete(user_id):
    if user_id == g.user["id"]:
        return jsonify({"error": "Eigenen Account nicht löschbar."}), 400
    deleted = _auth.get_user_by_id(user_id)
    _auth.delete_user(user_id)
    db.log_audit(g.user["id"], "user.deleted", f"user:{user_id}", deleted["username"] if deleted else "")
    return jsonify({"ok": True})

@blueprint.post("/api/users/<int:user_id>/password")
@_auth.admin_required
def api_users_set_password(user_id):
    data     = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen haben."}), 400
    _auth.set_password(user_id, password, must_change=True)
    db.log_audit(g.user["id"], "user.password_reset", f"user:{user_id}")
    return jsonify({"ok": True})

@blueprint.post("/api/users/<int:user_id>/download")
@_auth.admin_required
def api_users_set_download(user_id):
    data  = request.get_json(silent=True) or {}
    allow = bool(data.get("allow", False))
    _auth.set_allow_download(user_id, allow)
    db.log_audit(g.user["id"], "user.capability", f"user:{user_id}", f"download={allow}")
    return jsonify({"ok": True, "allow_download": allow})


@blueprint.post("/api/users/<int:user_id>/capability/<capability>")
@_auth.admin_required
def api_users_set_capability(user_id, capability):
    if capability not in ("playlists", "radio_stations", "download", "lyrics_edit"):
        return jsonify({"error": "unknown capability"}), 400
    allow = bool((request.get_json(silent=True) or {}).get("allow", False))
    _auth.set_user_capability(user_id, capability, allow)
    db.log_audit(g.user["id"], "user.capability", f"user:{user_id}", f"{capability}={allow}")
    return jsonify({"ok": True, "capability": capability, "allow": allow})


@blueprint.post("/api/users/<int:user_id>/active")
@_auth.admin_required
def api_users_set_active(user_id):
    if user_id == g.user["id"]:
        return jsonify({"error": "Eigenen Account nicht deaktivierbar."}), 400
    active = bool((request.get_json(silent=True) or {}).get("active", False))
    _auth.set_user_active(user_id, active)
    db.log_audit(g.user["id"], "user.active", f"user:{user_id}", str(active))
    return jsonify({"ok": True, "active": active})


@blueprint.post("/api/users/<int:user_id>/playcount")
@_auth.admin_required
def api_users_set_playcount(user_id):
    data = request.get_json(silent=True) or {}
    allow = bool(data.get("allow", False))
    _auth.set_contributes_playcount(user_id, allow)
    db.log_audit(g.user["id"], "user.playcount_contribution", f"user:{user_id}", str(allow))
    return jsonify({"ok": True, "contributes_playcount": allow})

@blueprint.get("/api/me-optional")
def api_me_optional():
    """Like /api/me but returns null instead of 401 — used by Radio Companion."""
    token = request.cookies.get(_auth.SESSION_COOKIE)
    if token:
        user = _auth.get_user_by_token(token)
        if user:
            is_admin = user["role"] == "admin"
            return jsonify({
                "id":             user["id"],
                "username":       user["username"],
                "role":           user["role"],
                "allow_download": is_admin or bool(user["allow_download"]),
                "allow_playlists": is_admin or _auth.can(user, "create_playlists"),
                "allow_radio_stations": is_admin or _auth.can(user, "create_radio_stations"),
                "allow_lyrics_edit": is_admin or _auth.can(user, "edit_lyrics"),
                "contributes_playcount": bool(user["contributes_playcount"]),
            })
    return jsonify(None)


@blueprint.get("/api/admin/blocked-ips")
@_auth.admin_required
def api_blocked_ips():
    return jsonify(_auth.get_blocked_ips())

@blueprint.delete("/api/admin/blocked-ips/<path:ip>")
@_auth.admin_required
def api_unblock_ip(ip):
    _auth.unblock_ip(ip)
    return jsonify({"ok": True})


ACCESS_SETTINGS = {
    "allow_anonymous_web": "0",
    "allow_user_playlists": "1",
    "allow_user_radio_stations": "1",
    "companion_access": "public",
}


@blueprint.get("/api/admin/access-settings")
@_auth.admin_required
def api_access_settings_get():
    return jsonify({key: db.get_setting(key, default) for key, default in ACCESS_SETTINGS.items()})


@blueprint.put("/api/admin/access-settings")
@_auth.admin_required
def api_access_settings_put():
    data = request.get_json(silent=True) or {}
    for key in ("allow_anonymous_web", "allow_user_playlists", "allow_user_radio_stations"):
        if key in data:
            db.set_setting(key, "1" if bool(data[key]) else "0")
    if "companion_access" in data:
        value = str(data["companion_access"])
        if value not in ("public", "authenticated", "disabled"):
            return jsonify({"error": "invalid companion_access"}), 400
        db.set_setting("companion_access", value)
    db.log_audit(g.user["id"], "access.settings_updated", "system")
    return api_access_settings_get()
