"""Settings and privacy-aware listening event collection for Adolar4U."""

from __future__ import annotations

import math


EVENT_TYPES = {"started", "skipped", "completed"}
EVENT_SOURCES = {"library", "playlist", "shuffle", "radio", "adolar4u", "unknown"}
EVENT_REASONS = {"manual_next", "track_change", "ended", "error", "stop", None}
GLOBAL_DEFAULTS = {
    "enabled": False,
    "audio_analysis": False,
    "collaborative": False,
}


def _db_module():
    import db
    return db


def _bool_setting(value) -> bool:
    return str(value or "0") == "1"


def get_global_settings() -> dict:
    db = _db_module()
    return {
        "enabled": _bool_setting(db.get_setting("adolar4u_enabled", "0")),
        "audio_analysis": _bool_setting(db.get_setting("adolar4u_audio_analysis", "0")),
        "collaborative": _bool_setting(db.get_setting("adolar4u_collaborative", "0")),
    }


def update_global_settings(values: dict) -> dict:
    db = _db_module()
    keys = {
        "enabled": "adolar4u_enabled",
        "audio_analysis": "adolar4u_audio_analysis",
        "collaborative": "adolar4u_collaborative",
    }
    for field, setting_key in keys.items():
        if field in values:
            db.set_setting(setting_key, "1" if bool(values[field]) else "0")
    return get_global_settings()


def get_user_settings(user_id: int) -> dict:
    db = _db_module()
    with db.db() as conn:
        row = conn.execute("""
            SELECT enabled, learning_paused, collaborative_enabled, discovery_level
            FROM adolar4u_user_settings WHERE user_id=?
        """, (int(user_id),)).fetchone()
    if not row:
        return {
            "enabled": False,
            "learning_paused": False,
            "collaborative_enabled": False,
            "discovery_level": 0.15,
        }
    return {
        "enabled": bool(row["enabled"]),
        "learning_paused": bool(row["learning_paused"]),
        "collaborative_enabled": bool(row["collaborative_enabled"]),
        "discovery_level": float(row["discovery_level"]),
    }


def update_user_settings(user_id: int, values: dict) -> dict:
    current = get_user_settings(user_id)
    for field in ("enabled", "learning_paused", "collaborative_enabled"):
        if field in values:
            current[field] = bool(values[field])
    if "discovery_level" in values:
        try:
            discovery = float(values["discovery_level"])
        except (TypeError, ValueError):
            raise ValueError("invalid discovery_level")
        if not math.isfinite(discovery) or not 0 <= discovery <= 1:
            raise ValueError("invalid discovery_level")
        current["discovery_level"] = discovery

    global_settings = get_global_settings()
    if current["collaborative_enabled"] and not global_settings["collaborative"]:
        current["collaborative_enabled"] = False

    db = _db_module()
    with db.db() as conn:
        conn.execute("""
            INSERT INTO adolar4u_user_settings
                (user_id, enabled, learning_paused, collaborative_enabled,
                 discovery_level, updated_at)
            VALUES (?, ?, ?, ?, ?, unixepoch())
            ON CONFLICT(user_id) DO UPDATE SET
                enabled=excluded.enabled,
                learning_paused=excluded.learning_paused,
                collaborative_enabled=excluded.collaborative_enabled,
                discovery_level=excluded.discovery_level,
                updated_at=excluded.updated_at
        """, (
            int(user_id), int(current["enabled"]), int(current["learning_paused"]),
            int(current["collaborative_enabled"]), current["discovery_level"],
        ))
    return current


def _nonnegative_number(value, field: str) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {field}")
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"invalid {field}")
    return result


def record_event(user_id: int, track_id: int, event: dict) -> dict:
    global_settings = get_global_settings()
    user_settings = get_user_settings(user_id)
    if not global_settings["enabled"]:
        return {"accepted": False, "reason": "module_disabled"}
    if not user_settings["enabled"]:
        return {"accepted": False, "reason": "user_disabled"}
    if user_settings["learning_paused"]:
        return {"accepted": False, "reason": "learning_paused"}

    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type not in EVENT_TYPES:
        raise ValueError("invalid event_type")
    source = str(event.get("source") or "unknown").strip().lower()
    if source not in EVENT_SOURCES:
        source = "unknown"
    reason = event.get("reason")
    reason = str(reason).strip().lower() if reason is not None else None
    if reason not in EVENT_REASONS:
        reason = None
    position = _nonnegative_number(event.get("position_seconds"), "position_seconds")
    duration = _nonnegative_number(event.get("duration_seconds"), "duration_seconds")
    ratio = min(1.0, position / duration) if duration > 0 else 0.0
    session_id = str(event.get("session_id") or "").strip()[:120] or None
    client_event_id = str(event.get("client_event_id") or "").strip()[:120] or None

    db = _db_module()
    with db.db() as conn:
        if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (int(track_id),)).fetchone():
            raise LookupError("track not found")
        cur = conn.execute("""
            INSERT OR IGNORE INTO adolar4u_listening_events
                (user_id, track_id, event_type, position_seconds, duration_seconds,
                 completion_ratio, source, reason, session_id, client_event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(user_id), int(track_id), event_type, position, duration, ratio,
            source, reason, session_id, client_event_id,
        ))
    return {"accepted": bool(cur.rowcount), "duplicate": cur.rowcount == 0}


def delete_profile(user_id: int) -> int:
    db = _db_module()
    with db.db() as conn:
        cur = conn.execute(
            "DELETE FROM adolar4u_listening_events WHERE user_id=?",
            (int(user_id),),
        )
    return cur.rowcount
