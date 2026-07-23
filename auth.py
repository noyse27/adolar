"""Authentication, session management and brute-force protection for Adolar."""
import os
import secrets
import threading
import time
from functools import wraps
from urllib.parse import quote

from flask import g, jsonify, redirect, request
from werkzeug.security import check_password_hash, generate_password_hash

import db

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
    "/login", "/setup",
    "/api/stream/", "/api/random", "/api/cover/",
    "/api/stats", "/api/disco-status", "/api/me-optional",
    "/api/radio/", "/api/radio-stations",
    "/api/search",   # read-only; called by Disco server without user session
    "/api/client/heartbeat",
    "/static/", "/hilfe/",
)
# Disco-specific endpoints (no session needed, called by Disco server)
PUBLIC_SUFFIXES = ("/disco-played",)

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
                      u.allow_radio_stations, u.contributes_playcount, u.is_active,
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

def get_all_users() -> list[dict]:
    with db.db() as conn:
        rows = conn.execute(
            """SELECT id, username, role, allow_download, allow_playlists,
                      allow_radio_stations, contributes_playcount, is_active,
                      must_change_password, created_at FROM users ORDER BY id"""
        ).fetchall()
    return [dict(r) for r in rows]

def get_user_by_id(user_id: int) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT id, username, role, allow_download, allow_playlists,
                      allow_radio_stations, contributes_playcount, is_active,
                      must_change_password FROM users WHERE id=?""",
            (user_id,)
        ).fetchone()
    return dict(row) if row else None

def get_user_by_name(username: str) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT id, username, password_hash, role, allow_download,
                      allow_playlists, allow_radio_stations, contributes_playcount,
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
    return any(path.endswith(suffix) for suffix in PUBLIC_SUFFIXES)


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

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        if g.user["role"] != "admin":
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated
