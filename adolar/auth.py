"""Authentication, session management and brute-force protection for Adolar."""
import hashlib
import os
import secrets
import threading
import time
from functools import wraps
from urllib.parse import quote

from flask import g, jsonify, redirect, request
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

# ── Constants ─────────────────────────────────────────────────────────────────
# Development-only bypass: every request runs as a local "dev-admin" account.
# Never set this in a production deployment; it disables authentication.
DEV_ADMIN_ENABLED = os.environ.get("ADOLAR_DEV_ADMIN", "").lower() in ("1", "true", "yes")
DEV_ADMIN_USERNAME = "dev-admin"

SESSION_COOKIE   = "adolar_session"
SESSION_TTL      = 2 * 3600          # 2 hours (without remember-me)
SESSION_TTL_LONG = 30 * 24 * 3600   # 30 days (remember-me)

# Brute-force thresholds
BF_WINDOW        = 5 * 60     # 5 minute rolling window
BF_SOFT_LIMIT    = 5          # attempts before soft-block
BF_SOFT_BLOCK    = 15 * 60    # 15 min block
BF_HARD_LIMIT    = 10         # attempts before permanent block
BF_HARD_BLOCK    = 253402300800  # permanent (year 9999); admin must unblock manually

# Routes that don't require authentication
PUBLIC_PREFIXES = (
    "/login", "/setup", "/health",
    "/api/stream/", "/api/random", "/api/cover/",
    "/api/stats", "/api/disco-status", "/api/me-optional",
    "/api/radio/", "/api/radio-stations",
    "/api/search", "/api/albums",   # read-only; called by Disco server without user session
    "/api/tracks/",                 # lyrics GET/fetch are public; writes check capability in-route
    "/api/client/heartbeat",
    # Not actually open: these authenticate via android_device_required's own
    # Bearer check (a device token, never the session cookie or api_tokens
    # this generic gate looks for), so they must bypass this gate rather than
    # being rejected here before the route decorator gets a chance to run.
    "/api/android/v1/tracks/match", "/api/android/v1/events/batch",
    "/static/", "/hilfe/",
)
# Disco-specific endpoints (no session needed, called by Disco server)
PUBLIC_SUFFIXES = ("/disco-played",)

# Every Adolar-family product identified via X-Adolar-Product (session
# login) or api_tokens.product (Bearer auth). Shared allowlist so new
# products get validated consistently instead of each call site hard-
# coding its own tuple (see docs/INTEGRATION_STANDARDS.md section 3).
KNOWN_PRODUCTS = frozenset({"adolar_web", "companion", "android", "taggster", "songster"})
# Disco-specific /api/track/<id>/... endpoints, matched by suffix on that prefix only
# (a bare suffix in PUBLIC_SUFFIXES would also expose unrelated admin routes, e.g.
# "/bpm" would match the admin-only /api/scan/bpm library rescan trigger).
PUBLIC_TRACK_SUFFIXES = ("/bpm",)

# ── In-memory brute-force tracker ─────────────────────────────────────────────
_bf_lock  = threading.Lock()
_bf_state: dict[str, dict] = {}   # ip -> {attempts: [...timestamps], blocked_until: float}

def _get_client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

def _bf_check(ip: str) -> tuple[bool, int]:
    """Returns (is_blocked, seconds_remaining)."""
    now = time.time()
    with _bf_lock:
        s = _bf_state.get(ip)
        if not s:
            return False, 0
        if s.get("blocked_until", 0) > now:
            return True, int(s["blocked_until"] - now)
        return False, 0

def _bf_record_failure(ip: str):
    now = time.time()
    with _bf_lock:
        s = _bf_state.setdefault(ip, {"attempts": [], "blocked_until": 0})
        # Purge old entries outside window
        s["attempts"] = [t for t in s["attempts"] if now - t < BF_WINDOW]
        s["attempts"].append(now)
        total = len(s["attempts"])
        if total >= BF_HARD_LIMIT:
            s["blocked_until"] = now + BF_HARD_BLOCK
            _persist_block(ip, s["blocked_until"])
        elif total >= BF_SOFT_LIMIT:
            s["blocked_until"] = now + BF_SOFT_BLOCK
            _persist_block(ip, s["blocked_until"])

def _bf_clear(ip: str):
    with _bf_lock:
        _bf_state.pop(ip, None)
    with db.db() as conn:
        conn.execute("DELETE FROM login_blocks WHERE ip=?", (ip,))

def _persist_block(ip: str, until: float):
    try:
        with db.db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO login_blocks (ip, blocked_until) VALUES (?,?)",
                (ip, until)
            )
    except Exception:
        pass

def load_persisted_blocks():
    """Called on startup to restore blocks that survived a restart."""
    now = time.time()
    try:
        with db.db() as conn:
            rows = conn.execute(
                "SELECT ip, blocked_until FROM login_blocks WHERE blocked_until > ?", (now,)
            ).fetchall()
        with _bf_lock:
            for row in rows:
                ip = row["ip"]
                s = _bf_state.setdefault(ip, {"attempts": [], "blocked_until": 0})
                s["blocked_until"] = row["blocked_until"]
    except Exception:
        pass

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_user_by_token(token: str) -> dict | None:
    now = time.time()
    with db.db() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.role, u.allow_download, u.allow_playlists,
                      u.allow_radio_stations, u.allow_lyrics_edit,
                      u.contributes_playcount, u.is_active,
                      u.must_change_password
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token=? AND s.expires_at > ? AND u.is_active=1""",
            (token, now)
        ).fetchone()
    return dict(row) if row else None

def create_session(user_id: int, remember: bool, product: str = "adolar_web",
                   ip_address: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    expires = now + (SESSION_TTL_LONG if remember else SESSION_TTL)
    with db.db() as conn:
        user = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        connection = conn.execute(
            """INSERT INTO connection_log
                   (user_id, username, product, ip_address, connected_at, last_seen_at)
               VALUES (?,?,?,?,?,?)""",
            (user_id, user["username"] if user else "Unbekannt", product,
             ip_address, now, now),
        )
        conn.execute(
            """INSERT INTO sessions (token, user_id, expires_at, connection_id)
               VALUES (?,?,?,?)""",
            (token, user_id, expires, connection.lastrowid)
        )
    return token


def touch_session(token: str) -> None:
    """Mark an authenticated client as active without extending its login."""
    now = time.time()
    with db.db() as conn:
        conn.execute(
            """UPDATE connection_log SET last_seen_at=?
               WHERE id=(SELECT connection_id FROM sessions WHERE token=?)""",
            (now, token),
        )

def delete_session(token: str):
    with db.db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))

def purge_expired_sessions():
    with db.db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))

# ── API tokens (admin tools, e.g. Adolar Taggster) ────────────────────────────
# Separate from session cookies: no expiry, explicit revocation, sent as
# 'Authorization: Bearer <token>'. See before_request().

def get_user_by_api_token(token: str) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.role, u.allow_download, u.allow_playlists,
                      u.allow_radio_stations, u.allow_lyrics_edit,
                      u.contributes_playcount, u.is_active,
                      u.must_change_password, t.product AS token_product
               FROM api_tokens t JOIN users u ON u.id = t.user_id
               WHERE t.token=? AND t.revoked_at IS NULL AND u.is_active=1""",
            (token,)
        ).fetchone()
    return dict(row) if row else None

def create_api_token(user_id: int, name: str = "", product: str = "taggster") -> str:
    """Create and return a new API token. The plaintext token is only ever
    available here at creation time — it is not retrievable afterwards.
    `product` scopes which product-specific API surface (e.g. /api/songster/*)
    this token may use; unrecognized values fall back to "taggster" (the
    original, pre-multi-product default) rather than silently accepting
    anything, matching KNOWN_PRODUCTS validation elsewhere."""
    token = secrets.token_urlsafe(32)
    product = product if product in KNOWN_PRODUCTS else "taggster"
    with db.db() as conn:
        conn.execute(
            "INSERT INTO api_tokens (token, user_id, name, product, created_at) VALUES (?,?,?,?,?)",
            (token, user_id, name or None, product, time.time())
        )
    return token

def touch_api_token(token: str, ip_address: str = "", client_version: str = "") -> None:
    """Update last_used_at and keep a connection_log entry for this token so
    it shows up in the admin 'Aktuelle Verbindungen' view, identified by the
    token's own product (see create_api_token) rather than a hardcoded value.
    One connection_log row per token, refreshed on every use (unlike
    sessions, which get a fresh row per login).

    A connection only counts as "current" (see app._monitor_connections) if
    it has a client_key set OR a linked non-expired session — API tokens have
    neither by default, so a stable client_key is required here, matching the
    same mechanism the companion/radio heartbeat uses (app._record_client_heartbeat).
    """
    now = time.time()
    with db.db() as conn:
        row = conn.execute(
            "SELECT id, connection_id, user_id, product FROM api_tokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return
        conn.execute("UPDATE api_tokens SET last_used_at=? WHERE token=?", (now, token))
        if row["connection_id"]:
            conn.execute(
                """UPDATE connection_log SET last_seen_at=?, ip_address=?,
                          client_version=COALESCE(?, client_version)
                   WHERE id=?""",
                (now, ip_address, client_version or None, row["connection_id"])
            )
        else:
            user = conn.execute("SELECT username FROM users WHERE id=?", (row["user_id"],)).fetchone()
            product = row["product"] or "taggster"
            client_key = f"{product}-token-{row['id']}"
            cur = conn.execute(
                """INSERT INTO connection_log
                       (user_id, username, product, ip_address, connected_at, last_seen_at,
                        client_key, client_version)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (row["user_id"], user["username"] if user else "Unbekannt", product,
                 ip_address, now, now, client_key, client_version or None),
            )
            conn.execute(
                "UPDATE api_tokens SET connection_id=? WHERE token=?", (cur.lastrowid, token)
            )

def revoke_api_token(token_id: int, user_id: int):
    """Revoke a token by its id, scoped to the owning user so one admin
    cannot revoke another admin's token by guessing an id."""
    with db.db() as conn:
        conn.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE id=? AND user_id=?",
            (time.time(), token_id, user_id)
        )

def list_api_tokens(user_id: int) -> list[dict]:
    """List a user's active tokens — never includes the plaintext token value."""
    with db.db() as conn:
        rows = conn.execute(
            """SELECT id, name, product, created_at, last_used_at FROM api_tokens
               WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC""",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]

# ── Android device tokens (background sync, e.g. Adolar Next) ─────────────────
# Separate from control.api_tokens (admin tools) and control.sessions
# (interactive screens): only a SHA-256 hash is stored, sent as
# 'Authorization: Bearer <token>' and checked by android_device_required
# below rather than the generic before_request() session/API-token flow.

def _hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_android_device_token(user_id: int, name: str = "") -> str:
    """Create and return a new Android device token. Like create_api_token,
    the plaintext value is only ever available here at creation time — only
    its hash is persisted."""
    token = secrets.token_urlsafe(32)
    with db.db() as conn:
        conn.execute(
            "INSERT INTO android_devices (token_hash, user_id, name, created_at) "
            "VALUES (?,?,?,?)",
            (_hash_device_token(token), user_id, name or None, time.time())
        )
    return token

def get_android_device_and_user(token: str) -> tuple[dict, dict] | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT d.id AS device_id, d.name AS device_name,
                      u.id, u.username, u.role, u.allow_download, u.allow_playlists,
                      u.allow_radio_stations, u.allow_lyrics_edit,
                      u.contributes_playcount, u.is_active,
                      u.must_change_password
               FROM android_devices d JOIN users u ON u.id = d.user_id
               WHERE d.token_hash=? AND d.revoked_at IS NULL AND u.is_active=1""",
            (_hash_device_token(token),)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    device = {"id": data.pop("device_id"), "name": data.pop("device_name")}
    return device, data

def touch_android_device_token(token: str) -> None:
    with db.db() as conn:
        conn.execute(
            "UPDATE android_devices SET last_used_at=? WHERE token_hash=?",
            (time.time(), _hash_device_token(token))
        )

def revoke_android_device_token(device_id: int, user_id: int):
    """Revoke a device by its id, scoped to the owning user."""
    with db.db() as conn:
        conn.execute(
            "UPDATE android_devices SET revoked_at=? WHERE id=? AND user_id=?",
            (time.time(), device_id, user_id)
        )

def list_android_devices(user_id: int) -> list[dict]:
    with db.db() as conn:
        rows = conn.execute(
            """SELECT id, name, created_at, last_used_at FROM android_devices
               WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC""",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_users() -> list[dict]:
    with db.db() as conn:
        rows = conn.execute(
            """SELECT id, username, role, allow_download, allow_playlists,
                      allow_radio_stations, allow_lyrics_edit,
                      contributes_playcount, is_active,
                      must_change_password, created_at FROM users ORDER BY id"""
        ).fetchall()
    return [dict(r) for r in rows]

def get_user_by_id(user_id: int) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT id, username, role, allow_download, allow_playlists,
                      allow_radio_stations, allow_lyrics_edit,
                      contributes_playcount, is_active,
                      must_change_password FROM users WHERE id=?""",
            (user_id,)
        ).fetchone()
    return dict(row) if row else None

def get_user_by_name(username: str) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT id, username, password_hash, role, allow_download,
                      allow_playlists, allow_radio_stations, allow_lyrics_edit,
                      contributes_playcount,
                      is_active, must_change_password
               FROM users WHERE LOWER(username)=LOWER(?)""",
            (username,)
        ).fetchone()
    return dict(row) if row else None

def user_count() -> int:
    with db.db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def create_user(username: str, password: str, role: str = "user") -> int:
    pw_hash = generate_password_hash(password)
    with db.db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) VALUES (?,?,?,1)",
            (username, pw_hash, role)
        )
        return cur.lastrowid

def set_password(user_id: int, password: str, must_change: bool = False):
    pw_hash = generate_password_hash(password)
    with db.db() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=? WHERE id=?",
            (pw_hash, 1 if must_change else 0, user_id)
        )

def set_allow_download(user_id: int, allow: bool):
    with db.db() as conn:
        conn.execute("UPDATE users SET allow_download=? WHERE id=?", (1 if allow else 0, user_id))


def set_user_capability(user_id: int, capability: str, allow: bool):
    columns = {
        "playlists": "allow_playlists",
        "radio_stations": "allow_radio_stations",
        "lyrics_edit": "allow_lyrics_edit",
        "download": "allow_download",
    }
    column = columns.get(capability)
    if not column:
        raise ValueError("unknown capability")
    with db.db() as conn:
        conn.execute(f"UPDATE users SET {column}=? WHERE id=?", (1 if allow else 0, user_id))


def set_user_active(user_id: int, active: bool):
    with db.db() as conn:
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def set_contributes_playcount(user_id: int, allow: bool):
    with db.db() as conn:
        conn.execute(
            "UPDATE users SET contributes_playcount=? WHERE id=?",
            (1 if allow else 0, user_id),
        )

def delete_user(user_id: int):
    with db.db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id IN (SELECT id FROM playlists WHERE owner_id=?)",
            (user_id,),
        )
        conn.execute("DELETE FROM playlists WHERE owner_id=?", (user_id,))
        # radio_stations.owner_id/created_by have no FK to users (they can't:
        # users lives in the separate control database — see db.CONTROL_DB_PATH),
        # so the CASCADE/SET NULL behavior those columns used to get from
        # SQLite is replicated here explicitly.
        conn.execute("DELETE FROM radio_stations WHERE owner_id=?", (user_id,))
        conn.execute(
            "UPDATE radio_stations SET created_by=NULL WHERE created_by=?", (user_id,),
        )
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))

def get_blocked_ips() -> list[dict]:
    now = time.time()
    with db.db() as conn:
        rows = conn.execute(
            "SELECT ip, blocked_until FROM login_blocks WHERE blocked_until > ? ORDER BY blocked_until DESC",
            (now,)
        ).fetchall()
    return [dict(r) for r in rows]

def unblock_ip(ip: str):
    _bf_clear(ip)

def verify_password(user: dict, password: str) -> bool:
    return check_password_hash(user["password_hash"], password)

# ── Flask middleware ──────────────────────────────────────────────────────────

def _is_public(path: str) -> bool:
    if any(path == prefix or path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return True
    if any(path.endswith(suffix) for suffix in PUBLIC_SUFFIXES):
        return True
    return path.startswith("/api/track/") and any(
        path.endswith(suffix) for suffix in PUBLIC_TRACK_SUFFIXES
    )


def setting_enabled(key: str, default: bool = False) -> bool:
    return str(db.get_setting(key, "1" if default else "0")).lower() in ("1", "true", "yes", "on")


def can(user: dict | None, capability: str) -> bool:
    if user and user.get("role") == "admin":
        return True
    if capability == "view_web":
        return bool(user) or setting_enabled("allow_anonymous_web")
    if capability == "create_playlists":
        return bool(user and setting_enabled("allow_user_playlists", True) and user.get("allow_playlists", 1))
    if capability == "create_radio_stations":
        return bool(user and setting_enabled("allow_user_radio_stations", True) and user.get("allow_radio_stations", 1))
    if capability == "download_tracks":
        return bool(user and user.get("allow_download"))
    if capability == "edit_lyrics":
        return bool(user and user.get("allow_lyrics_edit"))
    return False

def _get_dev_admin() -> dict | None:
    """Return (and lazily create) the local development admin account."""
    user = get_user_by_name(DEV_ADMIN_USERNAME)
    if user is None:
        pw_hash = generate_password_hash(secrets.token_urlsafe(32))
        with db.db() as conn:
            conn.execute(
                """INSERT INTO users (username, password_hash, role, must_change_password)
                   VALUES (?,?, 'admin', 0)""",
                (DEV_ADMIN_USERNAME, pw_hash),
            )
        user = get_user_by_name(DEV_ADMIN_USERNAME)
    if user:
        user.pop("password_hash", None)
    return user


def before_request():
    """Attach current user to g; redirect unauthenticated requests."""
    g.user = None
    g.token_product = None
    if request.method == "HEAD":
        return
    if DEV_ADMIN_ENABLED:
        g.user = _get_dev_admin()
        if g.user:
            return
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = get_user_by_token(token)
        if user:
            g.user = user
            touch_session(token)
            # Force password change before anything else
            if user["must_change_password"] and request.path not in ("/change-password", "/api/auth/change-password"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "must_change_password"}), 403
                return redirect("/change-password")
            return

    # API token (Bearer) — used by external admin tools instead of a browser
    # session cookie. No must-change-password gate: that's a web-UI concept.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_token = auth_header[7:].strip()
        if api_token:
            user = get_user_by_api_token(api_token)
            if user:
                g.token_product = user.pop("token_product", None)
                g.user = user
                touch_api_token(
                    api_token,
                    ip_address=_get_client_ip(),
                    client_version=request.headers.get("X-Adolar-Client-Version", ""),
                )
                return

    if _is_public(request.path):
        return

    if (request.method in ("GET", "HEAD")
            and request.path in ("/", "/miniplayer", "/api/genres", "/api/playlists", "/api/shuffle")
            and can(None, "view_web")):
        return
    if (request.method in ("GET", "HEAD")
            and request.path.startswith("/api/playlists/")
            and request.path.endswith("/tracks")
            and can(None, "view_web")):
        return
    if request.path == "/radio" and db.get_setting("companion_access", "public") == "public":
        return

    if request.path.startswith("/api/"):
        return jsonify({"error": "unauthorized"}), 401
    # Quote the path so it stays a query value and cannot smuggle a foreign
    # redirect target into /login (CodeQL py/url-redirection).
    return redirect("/login?next=" + quote(request.path, safe="/"))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

def android_device_required(f):
    """Guards Android background-sync endpoints: only a device-token Bearer
    header is accepted, never the session cookie (see auth-design note in
    the Priority-2 plan — background sync must survive a session expiring)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        result = get_android_device_and_user(token) if token else None
        if not result:
            return jsonify({"error": "unauthorized"}), 401
        g.device, g.user = result
        touch_android_device_token(token)
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        if g.user["role"] != "admin":
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated
