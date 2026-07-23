"""Settings and privacy-aware listening event collection for Adolar4U."""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict

import errors

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
            "discovery_level": 0.40,
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
            raise errors.ValidationError(
                "Ungültiges Entdeckungs-Level (Zahl zwischen 0 und 1 erwartet).") from None
        if not math.isfinite(discovery) or not 0 <= discovery <= 1:
            raise errors.ValidationError(
                "Ungültiges Entdeckungs-Level (Zahl zwischen 0 und 1 erwartet).")
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


def get_onboarding_state(user_id: int) -> dict:
    """Describe whether this user needs a cold-start taste profile."""
    db = _db_module()
    with db.db() as conn:
        row = conn.execute("""
            SELECT
                EXISTS(SELECT 1 FROM user_lastfm_accounts WHERE user_id=?) AS has_lastfm,
                EXISTS(SELECT 1 FROM user_play_counts WHERE user_id=? AND count>0) OR
                EXISTS(SELECT 1 FROM adolar4u_listening_events WHERE user_id=?) OR
                EXISTS(
                    SELECT 1 FROM playlist_tracks pt
                    JOIN playlists p ON p.id=pt.playlist_id
                    WHERE p.owner_id=?
                ) AS has_personal_data,
                EXISTS(
                    SELECT 1 FROM adolar4u_user_settings
                    WHERE user_id=? AND onboarding_completed_at IS NOT NULL
                ) AS completed
        """, (int(user_id),) * 5).fetchone()
        seeds = conn.execute("""
            SELECT kind, value FROM adolar4u_seed_preferences
            WHERE user_id=? ORDER BY kind, value COLLATE NOCASE
        """, (int(user_id),)).fetchall()
    artists = [row["value"] for row in seeds if row["kind"] == "artist"]
    genres = [row["value"] for row in seeds if row["kind"] == "genre"]
    completed = bool(row["completed"])
    has_lastfm = bool(row["has_lastfm"])
    has_personal_data = bool(row["has_personal_data"])
    return {
        "required": not completed and not has_lastfm and not has_personal_data,
        "completed": completed,
        "has_lastfm": has_lastfm,
        "has_personal_data": has_personal_data,
        "artists": artists,
        "genres": genres,
    }


def search_onboarding_options(kind: str, query: str = "", limit: int = 12) -> list[dict]:
    if kind not in ("artist", "genre"):
        raise errors.ValidationError("Unbekannte Onboarding-Kategorie (erwartet: artist oder genre).")
    column = "artist" if kind == "artist" else "genre"
    query = str(query or "").strip().casefold()
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    db = _db_module()
    with db.db() as conn:
        rows = conn.execute(f"""
            SELECT TRIM({column}) AS value, COUNT(*) AS track_count
            FROM tracks
            WHERE {column} IS NOT NULL AND TRIM({column}) != ''
              AND LOWER(TRIM({column})) LIKE ? ESCAPE '\\'
            GROUP BY LOWER(TRIM({column}))
            ORDER BY track_count DESC, value COLLATE NOCASE
            LIMIT ?
        """, (f"%{escaped}%", max(1, min(int(limit), 30)))).fetchall()
    return [dict(row) for row in rows]


def complete_onboarding(user_id: int, artists: list, genres: list) -> dict:
    labels = {"artists": "Künstler", "genres": "Genres"}

    def clean(values, field):
        if not isinstance(values, list):
            raise errors.ValidationError(f"Ungültige Liste für {labels[field]}.")
        result = []
        seen = set()
        for value in values:
            label = str(value or "").strip()
            key = label.casefold()
            if label and key not in seen:
                result.append(label)
                seen.add(key)
        if not 3 <= len(result) <= 5:
            raise errors.ValidationError(f"Bitte 3 bis 5 {labels[field]} auswählen.")
        return result

    artists = clean(artists, "artists")
    genres = clean(genres, "genres")
    db = _db_module()
    with db.db() as conn:
        valid_artists = {
            row["key"]: row["value"] for row in conn.execute("""
                SELECT LOWER(TRIM(artist)) AS key, MIN(TRIM(artist)) AS value
                FROM tracks WHERE artist IS NOT NULL AND TRIM(artist) != ''
                GROUP BY LOWER(TRIM(artist))
            """)
        }
        valid_genres = {
            row["key"]: row["value"] for row in conn.execute("""
                SELECT LOWER(TRIM(genre)) AS key, MIN(TRIM(genre)) AS value
                FROM tracks WHERE genre IS NOT NULL AND TRIM(genre) != ''
                GROUP BY LOWER(TRIM(genre))
            """)
        }
        if any(value.casefold() not in valid_artists for value in artists):
            raise errors.ValidationError(
                "Mindestens ein gewählter Künstler ist nicht in der Bibliothek.")
        if any(value.casefold() not in valid_genres for value in genres):
            raise errors.ValidationError(
                "Mindestens ein gewähltes Genre ist nicht in der Bibliothek.")

        conn.execute("DELETE FROM adolar4u_seed_preferences WHERE user_id=?", (int(user_id),))
        rows = [
            (int(user_id), "artist", valid_artists[value.casefold()], value.casefold(), 1.0)
            for value in artists
        ] + [
            (int(user_id), "genre", valid_genres[value.casefold()], value.casefold(), 1.0)
            for value in genres
        ]
        conn.executemany("""
            INSERT INTO adolar4u_seed_preferences
                (user_id, kind, value, value_norm, weight)
            VALUES (?, ?, ?, ?, ?)
        """, rows)
        conn.execute("""
            INSERT INTO adolar4u_user_settings
                (user_id, enabled, onboarding_completed_at, updated_at)
            VALUES (?, 1, unixepoch(), unixepoch())
            ON CONFLICT(user_id) DO UPDATE SET
                enabled=1,
                onboarding_completed_at=unixepoch(),
                updated_at=unixepoch()
        """, (int(user_id),))
    return get_onboarding_state(user_id)


def get_seed_affinities(user_id: int) -> tuple[dict[str, float], dict[str, float]]:
    db = _db_module()
    with db.db() as conn:
        rows = conn.execute("""
            SELECT kind, value_norm, weight FROM adolar4u_seed_preferences
            WHERE user_id=?
        """, (int(user_id),)).fetchall()
    artists = {row["value_norm"]: float(row["weight"]) for row in rows if row["kind"] == "artist"}
    genres = {row["value_norm"]: float(row["weight"]) for row in rows if row["kind"] == "genre"}
    return artists, genres


def _nonnegative_number(value, field: str) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        raise errors.ValidationError(
            f"Ungültiger Wert für '{field}' (nicht-negative Zahl erwartet).") from None
    if not math.isfinite(result) or result < 0:
        raise errors.ValidationError(f"Ungültiger Wert für '{field}' (nicht-negative Zahl erwartet).")
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
        raise errors.ValidationError(
            "Unbekannter Ereignistyp (erwartet: started, skipped oder completed).")
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
    recommendation_id = event.get("recommendation_id")
    try:
        recommendation_id = int(recommendation_id) if recommendation_id else None
    except (TypeError, ValueError):
        recommendation_id = None

    db = _db_module()
    with db.db() as conn:
        if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (int(track_id),)).fetchone():
            raise LookupError("track not found")
        if recommendation_id and not conn.execute("""
            SELECT 1 FROM adolar4u_recommendations
            WHERE id=? AND user_id=? AND track_id=?
        """, (recommendation_id, int(user_id), int(track_id))).fetchone():
            recommendation_id = None
        cur = conn.execute("""
            INSERT OR IGNORE INTO adolar4u_listening_events
                (user_id, track_id, event_type, position_seconds, duration_seconds,
                 completion_ratio, source, reason, session_id, client_event_id,
                 recommendation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(user_id), int(track_id), event_type, position, duration, ratio,
            source, reason, session_id, client_event_id, recommendation_id,
        ))
    return {"accepted": bool(cur.rowcount), "duplicate": cur.rowcount == 0}


def _json_object(value, default=None):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, dict) else (default or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        return default or {}


def _profile_delta(first: dict, latest: dict, field: str) -> list[dict]:
    before = {
        str(item.get("name")): float(item.get("weight") or 0)
        for item in first.get(field, []) if item.get("name")
    }
    after = {
        str(item.get("name")): float(item.get("weight") or 0)
        for item in latest.get(field, []) if item.get("name")
    }
    changes = [
        {
            "name": name,
            "before": round(before.get(name, 0.0), 4),
            "after": round(after.get(name, 0.0), 4),
            "delta": round(after.get(name, 0.0) - before.get(name, 0.0), 4),
        }
        for name in set(before) | set(after)
    ]
    changes.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return changes[:15]


def get_learning_history(user_id: int, days: int = 7, limit: int = 100) -> dict:
    """Return the private, explainable recommendation journal for one user."""
    days = max(1, min(int(days), 60))
    limit = max(1, min(int(limit), 200))
    now = time.time()
    start = now - days * 86400
    retention_start = now - 60 * 86400
    db = _db_module()

    with db.db() as conn:
        conn.execute("""
            DELETE FROM adolar4u_recommendation_batches
            WHERE user_id=? AND created_at < ?
        """, (int(user_id), retention_start))
        rows = conn.execute("""
            WITH outcomes AS (
                SELECT recommendation_id,
                       MAX(event_type='started') AS started,
                       MAX(event_type='completed') AS completed,
                       MAX(event_type='skipped') AS skipped,
                       MAX(CASE WHEN event_type IN ('completed','skipped')
                                THEN completion_ratio END) AS completion_ratio
                FROM adolar4u_listening_events
                WHERE user_id=? AND recommendation_id IS NOT NULL
                GROUP BY recommendation_id
            )
            SELECT r.id, r.bucket, r.diagnostics_json,
                   COALESCE(o.started, 0) AS started,
                   COALESCE(o.completed, 0) AS completed,
                   COALESCE(o.skipped, 0) AS skipped,
                   o.completion_ratio
            FROM adolar4u_recommendations r
            LEFT JOIN outcomes o ON o.recommendation_id=r.id
            WHERE r.user_id=? AND r.created_at>=?
            ORDER BY r.created_at DESC
        """, (int(user_id), int(user_id), start)).fetchall()
        recent = conn.execute("""
            WITH outcomes AS (
                SELECT recommendation_id,
                       MAX(event_type='started') AS started,
                       MAX(event_type='completed') AS completed,
                       MAX(event_type='skipped') AS skipped,
                       MAX(CASE WHEN event_type IN ('completed','skipped')
                                THEN completion_ratio END) AS completion_ratio
                FROM adolar4u_listening_events
                WHERE user_id=? AND recommendation_id IS NOT NULL
                GROUP BY recommendation_id
            )
            SELECT r.id, r.created_at, r.queue_position, r.candidate_rank,
                   r.bucket, r.reason, r.score, r.diagnostics_json,
                   t.id AS track_id, t.title, t.artist,
                   b.id AS batch_id, b.algorithm_version, b.discovery_level,
                   b.candidate_count, b.bucket_pool_json,
                   b.bucket_target_json, b.bucket_selected_json,
                   COALESCE(o.started, 0) AS started,
                   COALESCE(o.completed, 0) AS completed,
                   COALESCE(o.skipped, 0) AS skipped,
                   o.completion_ratio
            FROM adolar4u_recommendations r
            JOIN tracks t ON t.id=r.track_id
            JOIN adolar4u_recommendation_batches b ON b.id=r.batch_id
            LEFT JOIN outcomes o ON o.recommendation_id=r.id
            WHERE r.user_id=? AND r.created_at>=?
            ORDER BY r.created_at DESC, r.queue_position
            LIMIT ?
        """, (int(user_id), int(user_id), start, limit)).fetchall()
        first_batch = conn.execute("""
            SELECT created_at, profile_json FROM adolar4u_recommendation_batches
            WHERE user_id=? AND created_at>=? ORDER BY created_at ASC LIMIT 1
        """, (int(user_id), start)).fetchone()
        latest_batch = conn.execute("""
            SELECT created_at, profile_json, algorithm_version
            FROM adolar4u_recommendation_batches
            WHERE user_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 1
        """, (int(user_id), start)).fetchone()

    bucket_stats = {
        key: {"bucket": key, "count": 0, "completed": 0, "skipped": 0,
              "started": 0, "without_outcome": 0, "completion_sum": 0.0,
              "terminal_count": 0}
        for key in ("anchor", "similar", "familiar", "discovery")
    }
    positive_drivers: dict[str, float] = defaultdict(float)
    negative_drivers: dict[str, float] = defaultdict(float)
    outcomes = {"completed": 0, "skipped": 0, "started": 0, "without_outcome": 0}
    terminal_ratios = []

    for row in rows:
        stats = bucket_stats[row["bucket"]]
        stats["count"] += 1
        completed = bool(row["completed"])
        skipped = bool(row["skipped"])
        started = bool(row["started"])
        if completed:
            outcome = "completed"
        elif skipped:
            outcome = "skipped"
        elif started:
            outcome = "started"
        else:
            outcome = "without_outcome"
        outcomes[outcome] += 1
        stats[outcome] += 1
        if completed or skipped:
            ratio = float(row["completion_ratio"] or 0)
            terminal_ratios.append(ratio)
            stats["completion_sum"] += ratio
            stats["terminal_count"] += 1
        diagnostics = _json_object(row["diagnostics_json"])
        for key, value in diagnostics.get("bonuses", {}).items():
            positive_drivers[key] += float(value or 0)
        for key, value in diagnostics.get("penalties", {}).items():
            negative_drivers[key] += float(value or 0)
        positive_drivers["random"] += float(diagnostics.get("random_bonus") or 0)

    total = len(rows)
    buckets = []
    for stats in bucket_stats.values():
        terminal_count = stats.pop("terminal_count")
        completion_sum = stats.pop("completion_sum")
        stats["share"] = round(stats["count"] / total, 4) if total else 0.0
        stats["average_completion"] = (
            round(completion_sum / terminal_count, 4) if terminal_count else None
        )
        buckets.append(stats)

    def ranked_drivers(values: dict[str, float]) -> list[dict]:
        return [
            {"key": key, "average": round(value / total, 4)}
            for key, value in sorted(values.items(), key=lambda item: item[1], reverse=True)
            if total and value
        ]

    first_profile = _json_object(first_batch["profile_json"]) if first_batch else {}
    latest_profile = _json_object(latest_batch["profile_json"]) if latest_batch else {}
    recommendations = []
    for row in recent:
        item = dict(row)
        item["diagnostics"] = _json_object(item.pop("diagnostics_json"))
        item["bucket_pool"] = _json_object(item.pop("bucket_pool_json"))
        item["bucket_target"] = _json_object(item.pop("bucket_target_json"))
        item["bucket_selected"] = _json_object(item.pop("bucket_selected_json"))
        if item.pop("completed"):
            item["outcome"] = "completed"
        elif item.pop("skipped"):
            item["outcome"] = "skipped"
        elif item.pop("started"):
            item["outcome"] = "started"
        else:
            item["outcome"] = "without_outcome"
        recommendations.append(item)

    return {
        "days": days,
        "retention_days": 60,
        "summary": {
            "recommendations": total,
            "outcomes": outcomes,
            "average_completion": (
                round(sum(terminal_ratios) / len(terminal_ratios), 4)
                if terminal_ratios else None
            ),
            "early_skips": sum(
                bool(row["skipped"]) and float(row["completion_ratio"] or 0) < 0.25
                for row in rows
            ),
            "buckets": buckets,
            "positive_drivers": ranked_drivers(positive_drivers),
            "negative_drivers": ranked_drivers(negative_drivers),
        },
        "profile": {
            "first_at": first_batch["created_at"] if first_batch else None,
            "latest_at": latest_batch["created_at"] if latest_batch else None,
            "algorithm_version": latest_batch["algorithm_version"] if latest_batch else None,
            "latest": latest_profile,
            "artist_changes": _profile_delta(first_profile, latest_profile, "artists"),
            "genre_changes": _profile_delta(first_profile, latest_profile, "genres"),
        },
        "recommendations": recommendations,
    }


def delete_profile(user_id: int) -> int:
    db = _db_module()
    with db.db() as conn:
        cur = conn.execute(
            "DELETE FROM adolar4u_listening_events WHERE user_id=?",
            (int(user_id),),
        )
        conn.execute(
            "DELETE FROM adolar4u_recommendation_batches WHERE user_id=?",
            (int(user_id),),
        )
        conn.execute(
            "DELETE FROM adolar4u_seed_preferences WHERE user_id=?",
            (int(user_id),),
        )
        conn.execute("""
            UPDATE adolar4u_user_settings SET onboarding_completed_at=NULL
            WHERE user_id=?
        """, (int(user_id),))
    return cur.rowcount
