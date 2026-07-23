"""Portable, user-scoped analysis export for the private learning journal."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time
import zipfile


BUCKETS = ("anchor", "similar", "familiar", "discovery")
BONUS_KEYS = (
    "play_count", "explicit_favorite", "personal_playlist",
    "completed_history", "same_hour", "artist_affinity", "genre_affinity",
    "average_completion", "rediscovery", "discovery",
)
PENALTY_KEYS = ("early_skip", "skip_history", "recency")
FACT_KEYS = (
    "user_play_count", "completed_count", "skipped_count", "early_skip_count",
    "average_completion", "last_played_at", "hours_since_played",
    "lastfm_loved", "library_loved", "local_favorite", "personal_playlist",
    "artist_affinity", "genre_affinity",
)


def _db_module():
    import db
    return db


def _json_object(value) -> dict:
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _iso(epoch) -> str:
    if epoch is None:
        return ""
    return dt.datetime.fromtimestamp(float(epoch), dt.timezone.utc).isoformat(
        timespec="seconds"
    )


def _csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    # BOM makes artist/title Unicode reliable when the CSV is opened in Excel.
    return stream.getvalue().encode("utf-8-sig")


def _recommendation_rows(conn, user_id: int, start: float) -> list[dict]:
    rows = conn.execute("""
        WITH outcomes AS (
            SELECT recommendation_id,
                   COUNT(*) AS event_count,
                   MAX(event_type='started') AS started,
                   MAX(event_type='completed') AS completed,
                   MAX(event_type='skipped') AS skipped,
                   MAX(CASE WHEN event_type IN ('completed','skipped')
                            THEN completion_ratio END) AS completion_ratio
            FROM adolar4u_listening_events
            WHERE user_id=? AND recommendation_id IS NOT NULL
            GROUP BY recommendation_id
        )
        SELECT r.id AS recommendation_id, r.batch_id, r.created_at,
               r.queue_position, r.candidate_rank, r.bucket, r.reason, r.score,
               r.diagnostics_json, t.id AS track_id, t.artist, t.title,
               t.album, t.genre, t.year, t.duration,
               b.algorithm_version, b.candidate_count, b.discovery_level,
               COALESCE(o.event_count, 0) AS event_count,
               COALESCE(o.started, 0) AS started,
               COALESCE(o.completed, 0) AS completed,
               COALESCE(o.skipped, 0) AS skipped,
               o.completion_ratio
        FROM adolar4u_recommendations r
        JOIN tracks t ON t.id=r.track_id
        JOIN adolar4u_recommendation_batches b ON b.id=r.batch_id
        LEFT JOIN outcomes o ON o.recommendation_id=r.id
        WHERE r.user_id=? AND r.created_at>=?
        ORDER BY r.created_at, r.queue_position
    """, (user_id, user_id, start)).fetchall()
    exported = []
    for source in rows:
        row = dict(source)
        diagnostics = _json_object(row.pop("diagnostics_json"))
        bonuses = diagnostics.get("bonuses") or {}
        penalties = diagnostics.get("penalties") or {}
        facts = diagnostics.get("facts") or {}
        completed = bool(row.pop("completed"))
        skipped = bool(row.pop("skipped"))
        started = bool(row.pop("started"))
        row["created_at_iso"] = _iso(row["created_at"])
        row["outcome"] = (
            "completed" if completed else "skipped" if skipped
            else "started" if started else "without_outcome"
        )
        row["random_bonus"] = diagnostics.get("random_bonus")
        row["positive_total"] = diagnostics.get("positive_total")
        row["negative_total"] = diagnostics.get("negative_total")
        for key in BONUS_KEYS:
            row[f"bonus_{key}"] = bonuses.get(key)
        for key in PENALTY_KEYS:
            row[f"penalty_{key}"] = penalties.get(key)
        for key in FACT_KEYS:
            row[f"fact_{key}"] = facts.get(key)
        row["bonuses_json"] = json.dumps(bonuses, ensure_ascii=False, sort_keys=True)
        row["penalties_json"] = json.dumps(penalties, ensure_ascii=False, sort_keys=True)
        row["facts_json"] = json.dumps(facts, ensure_ascii=False, sort_keys=True)
        exported.append(row)
    return exported


def _event_rows(conn, user_id: int, start: float) -> list[dict]:
    rows = conn.execute("""
        SELECT e.id AS event_id, e.created_at, e.event_type, e.track_id,
               t.artist, t.title, t.album, t.genre,
               e.position_seconds, e.duration_seconds, e.completion_ratio,
               e.source, e.reason, e.recommendation_id,
               r.bucket AS recommendation_bucket,
               r.reason AS recommendation_reason,
               r.score AS recommendation_score
        FROM adolar4u_listening_events e
        JOIN tracks t ON t.id=e.track_id
        LEFT JOIN adolar4u_recommendations r
               ON r.id=e.recommendation_id AND r.user_id=e.user_id
        WHERE e.user_id=? AND e.created_at>=?
        ORDER BY e.created_at, e.id
    """, (user_id, start)).fetchall()
    exported = []
    for source in rows:
        row = dict(source)
        row["created_at_iso"] = _iso(row["created_at"])
        exported.append(row)
    return exported


def _batch_rows(conn, user_id: int, start: float) -> list[dict]:
    rows = conn.execute("""
        SELECT id AS batch_id, created_at, algorithm_version, requested_count,
               candidate_count, discovery_level, bucket_pool_json,
               bucket_target_json, bucket_selected_json, profile_json
        FROM adolar4u_recommendation_batches
        WHERE user_id=? AND created_at>=?
        ORDER BY created_at, id
    """, (user_id, start)).fetchall()
    exported = []
    for source in rows:
        row = dict(source)
        pool = _json_object(row.pop("bucket_pool_json"))
        target = _json_object(row.pop("bucket_target_json"))
        selected = _json_object(row.pop("bucket_selected_json"))
        profile = _json_object(row.pop("profile_json"))
        signals = profile.get("signals") or {}
        row["created_at_iso"] = _iso(row["created_at"])
        for bucket in BUCKETS:
            row[f"pool_{bucket}"] = pool.get(bucket, 0)
            row[f"target_{bucket}"] = target.get(bucket, 0)
            row[f"selected_{bucket}"] = selected.get(bucket, 0)
        row["profile_artists_json"] = json.dumps(
            profile.get("artists") or [], ensure_ascii=False, sort_keys=True,
        )
        row["profile_genres_json"] = json.dumps(
            profile.get("genres") or [], ensure_ascii=False, sort_keys=True,
        )
        row["profile_signals_json"] = json.dumps(
            signals, ensure_ascii=False, sort_keys=True,
        )
        exported.append(row)
    return exported


def build_learning_export(user_id: int, days: int = 60, app_version: str = "unknown"):
    """Return ``(BytesIO, filename)`` for one user's complete analysis window."""
    from .service import get_learning_history, get_user_settings

    days = max(1, min(int(days), 60))
    generated_at = time.time()
    start = generated_at - days * 86400
    db = _db_module()
    with db.db() as conn:
        recommendations = _recommendation_rows(conn, int(user_id), start)
        events = _event_rows(conn, int(user_id), start)
        batches = _batch_rows(conn, int(user_id), start)

    history = get_learning_history(int(user_id), days, limit=1)
    summary = {
        "export_format_version": 1,
        "app_version": app_version,
        "generated_at": _iso(generated_at),
        "period_days": days,
        "period_start": _iso(start),
        "retention_days": history.get("retention_days", 60),
        "user_settings": get_user_settings(int(user_id)),
        "row_counts": {
            "recommendations": len(recommendations),
            "listening_events": len(events),
            "profile_batches": len(batches),
        },
        "summary": history.get("summary", {}),
        "profile": history.get("profile", {}),
        "privacy": (
            "Enthält ausschließlich Lerndaten des exportierenden Adolar-Benutzers; "
            "keine Passwörter, Last.fm-Sitzungsschlüssel oder Musikdateipfade."
        ),
    }

    recommendation_fields = [
        "recommendation_id", "batch_id", "created_at_iso", "created_at",
        "algorithm_version", "track_id", "artist", "title", "album", "genre",
        "year", "duration", "queue_position", "candidate_rank",
        "candidate_count", "bucket", "reason", "score", "discovery_level",
        "outcome", "completion_ratio", "event_count", "random_bonus",
        "positive_total", "negative_total",
        *[f"bonus_{key}" for key in BONUS_KEYS],
        *[f"penalty_{key}" for key in PENALTY_KEYS],
        *[f"fact_{key}" for key in FACT_KEYS],
        "bonuses_json", "penalties_json", "facts_json",
    ]
    event_fields = [
        "event_id", "created_at_iso", "created_at", "event_type", "track_id",
        "artist", "title", "album", "genre", "position_seconds",
        "duration_seconds", "completion_ratio", "source", "reason",
        "recommendation_id", "recommendation_bucket", "recommendation_reason",
        "recommendation_score",
    ]
    batch_fields = [
        "batch_id", "created_at_iso", "created_at", "algorithm_version",
        "requested_count", "candidate_count", "discovery_level",
        *[f"pool_{key}" for key in BUCKETS],
        *[f"target_{key}" for key in BUCKETS],
        *[f"selected_{key}" for key in BUCKETS],
        "profile_artists_json", "profile_genres_json", "profile_signals_json",
    ]
    readme = """Adolar4U-Lerndatenexport
===========================

summary.json
  Aggregierte Kandidatengruppen, Reaktionen, Profiländerungen und Exportdaten.

recommendations.csv
  Jede Empfehlung mit Track-Metadaten, Score, Gruppe, Ausgang sowie allen
  positiven Einflüssen, Abzügen und Fakten der damaligen Entscheidung.

listening-events.csv
  Erfasste Starts, Abbrüche und vollständig gehörte Titel. Verknüpfte
  recommendation_id-Werte verbinden die Reaktion mit recommendations.csv.

profile-batches.csv
  Kandidatenpools, Ziel-/Ist-Anteile und Geschmacksprofil jeder erzeugten Queue.

Alle CSV-Dateien entsprechen Standard-CSV mit Komma als Trennzeichen und
UTF-8-BOM für Excel. Zeitpunkte stehen als ISO-8601/UTC und Unix-Epoch bereit.
Der Export enthält keine Passwörter, Last.fm-Sitzungsschlüssel oder Dateipfade.
"""

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("README.txt", readme.encode("utf-8"))
        zip_file.writestr(
            "summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        zip_file.writestr(
            "recommendations.csv", _csv_bytes(recommendations, recommendation_fields),
        )
        zip_file.writestr(
            "listening-events.csv", _csv_bytes(events, event_fields),
        )
        zip_file.writestr(
            "profile-batches.csv", _csv_bytes(batches, batch_fields),
        )
    archive.seek(0)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return archive, f"adolar4u-lerndaten-{stamp}-{days}tage.zip"

