"""Isolated demo-mode support: periodic reset, seeding, and destructive-action
blocking for a public demo deployment (see docker-compose.demo.yml and
docs/demo.md). Mirrors the existing ADOLAR_DEV_ADMIN env-var convention (see
auth.DEV_ADMIN_ENABLED) but locks the instance down instead of opening it up.
"""
import logging
import os
import time as _time
from functools import wraps

from flask import jsonify

from . import auth as _auth
from . import db

log = logging.getLogger(__name__)

DEMO_MODE = os.environ.get("ADOLAR_DEMO_MODE", "").lower() in ("1", "true", "yes")

_DEFAULT_RESET_MINUTES = 60
_MIN_RESET_MINUTES = 5
_MAX_RESET_MINUTES = 1440


def _parse_reset_minutes() -> int:
    try:
        raw = int(os.environ.get("ADOLAR_DEMO_RESET_MINUTES", _DEFAULT_RESET_MINUTES))
    except ValueError:
        raw = _DEFAULT_RESET_MINUTES
    return max(_MIN_RESET_MINUTES, min(_MAX_RESET_MINUTES, raw))


DEMO_RESET_MINUTES = _parse_reset_minutes()

# Fixed, publicly-documented demo credentials (see docs/demo.md and the
# frontend banner) - safe only because a demo deployment never holds real
# data and resets on its own schedule.
DEMO_ADMIN_USERNAME = os.environ.get("ADOLAR_DEMO_ADMIN_USERNAME", "demo-admin")
DEMO_ADMIN_PASSWORD = os.environ.get("ADOLAR_DEMO_ADMIN_PASSWORD", "adolar-demo")
DEMO_USER_USERNAME = os.environ.get("ADOLAR_DEMO_USER_USERNAME", "demo-hoerer")
DEMO_USER_PASSWORD = os.environ.get("ADOLAR_DEMO_USER_PASSWORD", "adolar-demo")

# Marks a database as "this is a demo instance I'm allowed to manage" -
# written by the first successful reset/seed and checked on every startup
# (see assert_demo_safe_to_manage). Without this, turning ADOLAR_DEMO_MODE=1
# on against an already-populated database (a copy-pasted production
# DB_PATH, a mistaken env file) would otherwise silently start periodically
# wiping real user data and the real music library's scan state.
_MARKER_KEY = "demo_managed"
_MARKER_VALUE = "1"

# Content tables holding user/listening activity - cleared on every demo
# cycle. tracks is first: everything else that references it cascades via
# ON DELETE CASCADE (playlist_tracks, user_play_counts, track_lyrics,
# songster_playlist_tracks/queue). android_track_links/event_receipts have
# no FK to tracks worth relying on (track_id is nullable there) so they're
# cleared explicitly. covers are content-addressed and reused across scans,
# so they're cleared too rather than accumulating forever.
_CONTENT_WIPE_STATEMENTS = (
    "DELETE FROM playlists",
    "DELETE FROM radio_stations",
    "DELETE FROM tracks",
    "DELETE FROM covers",
    "DELETE FROM android_track_links",
    "DELETE FROM android_event_receipts",
)
# Control tables holding accounts/sessions/history - users last, since
# api_tokens/android_devices/sessions/audit_log/lastfm tables reference it.
_CONTROL_WIPE_STATEMENTS = (
    "DELETE FROM sessions",
    "DELETE FROM api_tokens",
    "DELETE FROM android_devices",
    "DELETE FROM connection_log",
    "DELETE FROM login_blocks",
    "DELETE FROM audit_log",
    "DELETE FROM task_history",
    "DELETE FROM user_lastfm_accounts",
    "DELETE FROM lastfm_loved_tracks",
    "DELETE FROM user_lastfm_sync_jobs",
    "DELETE FROM users",
)

_last_reset_at: float | None = None


def _seed_demo_library(music_root: str) -> int:
    """Synchronously (re-)scans music_root into the tracks table.

    Reuses scanner's own file-collection and tag-parsing helpers directly
    instead of scanner.run_scan()'s background thread, so the freshly reset
    database has its demo tracks before the reset finishes rather than
    racing a visitor's first page load.
    """
    from . import scanner  # local import: avoids a demo_mode <-> scanner cycle

    count = 0
    for path in scanner._collect_mp3s(music_root):  # noqa: SLF001 - same-package reuse
        data = scanner._scan_file(path)  # noqa: SLF001 - same-package reuse
        if data:
            db.upsert_track(data)
            count += 1
    return count


def reset_demo_data() -> None:
    """Wipes every account/track/playlist/etc. and reseeds fixed demo data.

    Safe to call repeatedly (idempotent reseed) and safe to call on a fresh,
    empty database (the DELETEs are then no-ops).
    """
    global _last_reset_at
    from . import application as core  # local import: application imports this module

    with db.db() as conn:
        for statement in _CONTENT_WIPE_STATEMENTS:
            conn.execute(statement)
        for statement in _CONTROL_WIPE_STATEMENTS:
            conn.execute(statement)

    # Re-creates the system playlists DELETE FROM playlists just removed
    # (see db.init_db's _seed_system_playlists call) - cheap and idempotent.
    db.init_db()

    admin_id = _auth.create_user(DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, role="admin")
    _auth.set_password(admin_id, DEMO_ADMIN_PASSWORD, must_change=False)
    _auth.set_allow_download(admin_id, True)
    user_id = _auth.create_user(DEMO_USER_USERNAME, DEMO_USER_PASSWORD, role="user")
    _auth.set_password(user_id, DEMO_USER_PASSWORD, must_change=False)
    for capability in ("playlists", "radio_stations"):
        _auth.set_user_capability(user_id, capability, True)

    track_count = _seed_demo_library(core.MUSIC_ROOT)
    db.set_setting(_MARKER_KEY, _MARKER_VALUE)
    _last_reset_at = _time.time()
    log.info(
        "demo reset complete: seeded %d demo track(s) from %s",
        track_count, core.MUSIC_ROOT,
    )


def assert_demo_safe_to_manage() -> None:
    """Refuses to let demo mode manage a database that isn't already
    demo-managed and isn't empty - the only two states in which periodically
    wiping every user/track is safe. Call once at startup before scheduling
    periodic resets."""
    if db.get_setting(_MARKER_KEY) is not None:
        return
    existing_users = _auth.user_count()
    if existing_users == 0:
        reset_demo_data()
        return
    raise RuntimeError(
        f"ADOLAR_DEMO_MODE is enabled but this database already has {existing_users} user "
        "account(s) and no demo marker - refusing to start, since periodic demo resets "
        "would otherwise wipe real data. ADOLAR_DEMO_MODE must only be used against a "
        "fresh, isolated database (see docker-compose.demo.yml / docs/demo.md), never "
        "against an existing production database."
    )


def demo_reset_scheduler_loop() -> None:
    """Runs forever in a daemon thread, mirroring application.py's other
    while-True/sleep(300) schedulers (backup, play-count tags)."""
    interval_seconds = DEMO_RESET_MINUTES * 60
    while True:
        _time.sleep(300)
        if _last_reset_at is None or (_time.time() - _last_reset_at) >= interval_seconds:
            try:
                reset_demo_data()
            except Exception:
                log.exception("demo reset failed")


def demo_status() -> dict:
    if not DEMO_MODE:
        return {"active": False}
    next_reset_at = (_last_reset_at + DEMO_RESET_MINUTES * 60) if _last_reset_at else None
    return {
        "active": True,
        "reset_interval_minutes": DEMO_RESET_MINUTES,
        "last_reset_at": _last_reset_at,
        "next_reset_at": next_reset_at,
        "admin_username": DEMO_ADMIN_USERNAME,
        "admin_password": DEMO_ADMIN_PASSWORD,
        "user_username": DEMO_USER_USERNAME,
        "user_password": DEMO_USER_PASSWORD,
    }


def block_when_demo(action: str):
    """Route decorator: blocks a destructive admin action in demo mode.

    Applied to individual admin routes (see routes/admin.py) rather than a
    blanket gate, so read-only admin views (monitor, audit log, blocked-IP
    list) and low-risk actions (creating API/device tokens, editing user
    capabilities) keep working normally in the demo.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if DEMO_MODE:
                return jsonify({"error": f"{action} ist im Demomodus deaktiviert."}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
