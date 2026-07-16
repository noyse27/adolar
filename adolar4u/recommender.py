"""Explainable, metadata-first recommendation engine for the Adolar4U MVP."""

from __future__ import annotations

import math
import os
import random
import time

import smart_shuffle

from .service import get_global_settings, get_user_settings


def _db_module():
    import db
    return db


def _key(value) -> str:
    return str(value or "").strip().casefold()


def _candidate_query(order_by: str) -> str:
    return f"""
        WITH event_summary AS (
            SELECT track_id,
                   SUM(event_type='completed') AS completed_count,
                   SUM(event_type='skipped') AS skipped_count,
                   SUM(event_type='skipped' AND completion_ratio < 0.25) AS early_skips,
                   AVG(CASE WHEN event_type IN ('completed', 'skipped')
                            THEN completion_ratio END) AS avg_completion,
                   SUM(event_type='completed' AND
                       CAST(strftime('%H', created_at, 'unixepoch', 'localtime') AS INTEGER)=?)
                       AS same_hour_completed,
                   MAX(created_at) AS last_event_at
            FROM adolar4u_listening_events
            WHERE user_id=?
            GROUP BY track_id
        )
        SELECT t.id, t.path, t.title, t.artist, t.album, t.genre, t.year,
               t.track_no, t.duration, t.bitrate, t.size, t.cover_hash, t.bpm,
               t.loved, COALESCE(upc.count, 0) AS user_play_count,
               upc.last_played_at,
               COALESCE(ev.completed_count, 0) AS completed_count,
               COALESCE(ev.skipped_count, 0) AS skipped_count,
               COALESCE(ev.early_skips, 0) AS early_skips,
               COALESCE(ev.avg_completion, 0) AS avg_completion,
               COALESCE(ev.same_hour_completed, 0) AS same_hour_completed,
               ev.last_event_at,
               EXISTS(
                   SELECT 1 FROM playlist_tracks plt
                   JOIN playlists pl ON pl.id=plt.playlist_id
                   WHERE plt.track_id=t.id AND pl.owner_id=?
               ) AS in_personal_playlist,
               (COALESCE(upc.count, 0) * 2 + t.loved * 10
                + COALESCE(ev.completed_count, 0) * 3
                - COALESCE(ev.early_skips, 0) * 4
                + CASE WHEN EXISTS(
                    SELECT 1 FROM playlist_tracks plt2
                    JOIN playlists pl2 ON pl2.id=plt2.playlist_id
                    WHERE plt2.track_id=t.id AND pl2.owner_id=?
                  ) THEN 8 ELSE 0 END) AS signal_strength
        FROM tracks t
        LEFT JOIN user_play_counts upc
               ON upc.track_id=t.id AND upc.user_id=?
        LEFT JOIN event_summary ev ON ev.track_id=t.id
        ORDER BY {order_by}
        LIMIT ?
    """


def _load_candidates(user_id: int, limit: int = 2500) -> tuple[list[dict], dict]:
    db = _db_module()
    hour = time.localtime().tm_hour
    params = [hour, user_id, user_id, user_id, user_id]
    with db.db() as conn:
        stats = dict(conn.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT LOWER(TRIM(artist))) AS artists,
                   COUNT(DISTINCT CASE WHEN TRIM(album) != '' THEN
                       COALESCE(LOWER(TRIM(artist)), '') || CHAR(31) ||
                       LOWER(TRIM(album)) END) AS albums,
                   COUNT(DISTINCT CASE WHEN TRIM(genre) != '' THEN
                       LOWER(TRIM(genre)) END) AS genres
            FROM tracks
        """).fetchone())
        signal_rows = conn.execute(
            _candidate_query("signal_strength DESC, RANDOM()"),
            params + [min(600, limit)],
        ).fetchall()
        random_rows = conn.execute(
            _candidate_query("RANDOM()"),
            params + [limit],
        ).fetchall()

    candidates = {}
    for row in [*signal_rows, *random_rows]:
        candidates[int(row["id"])] = dict(row)
    return list(candidates.values()), stats


def _affinity_maps(candidates: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    artists: dict[str, float] = {}
    genres: dict[str, float] = {}
    for row in candidates:
        positive = (
            float(row["user_play_count"] or 0)
            + float(row["completed_count"] or 0) * 1.5
            + (3.0 if row["loved"] else 0.0)
            + (2.0 if row["in_personal_playlist"] else 0.0)
            - float(row["early_skips"] or 0) * 0.75
        )
        if positive <= 0:
            continue
        artist = _key(row["artist"])
        genre = _key(row["genre"])
        if artist:
            artists[artist] = artists.get(artist, 0.0) + positive
        if genre:
            genres[genre] = genres.get(genre, 0.0) + positive

    def normalize(values: dict[str, float]) -> dict[str, float]:
        maximum = max(values.values(), default=0.0)
        if maximum <= 0:
            return {}
        denominator = math.log1p(maximum)
        return {key: math.log1p(value) / denominator for key, value in values.items()}

    return normalize(artists), normalize(genres)


def _score_candidate(row: dict, artist_affinity: dict, genre_affinity: dict,
                     discovery: float, rng, now: float) -> tuple[float, str]:
    components: list[tuple[float, str]] = []
    plays = int(row["user_play_count"] or 0)
    completed = int(row["completed_count"] or 0)
    skipped = int(row["skipped_count"] or 0)
    early_skips = int(row["early_skips"] or 0)

    if plays:
        components.append((math.log1p(plays) * 1.35, "Häufig gehört"))
    if row["loved"]:
        components.append((4.0, "Favorit"))
    if row["in_personal_playlist"]:
        components.append((2.6, "In deinen Playlists"))
    if completed:
        components.append((min(3.0, math.log1p(completed) * 1.25),
                           "Oft vollständig gehört"))
    if row["same_hour_completed"]:
        components.append((min(1.5, float(row["same_hour_completed"]) * 0.35),
                           "Passt zu dieser Tageszeit"))

    artist_fit = artist_affinity.get(_key(row["artist"]), 0.0) * 2.2
    genre_fit = genre_affinity.get(_key(row["genre"]), 0.0) * 1.5
    if artist_fit:
        components.append((artist_fit, "Passender Künstler"))
    if genre_fit:
        components.append((genre_fit, "Passendes Genre"))

    event_total = completed + skipped
    negative = 0.0
    if event_total:
        negative += (early_skips / event_total) * 5.0
        negative += (skipped / event_total) * 1.5
        components.append((float(row["avg_completion"] or 0) * 1.2,
                           "Hohe Hördauer"))

    last_played = row["last_played_at"] or row["last_event_at"]
    rediscovery = 0.0
    if last_played:
        age = max(0.0, now - float(last_played))
        if age < 6 * 3600:
            negative += 4.0
        elif age < 24 * 3600:
            negative += 2.5
        elif age < 7 * 86400:
            negative += 1.0
        elif age > 30 * 86400 and (plays or completed):
            rediscovery = 0.9
            components.append((rediscovery, "Lange nicht gehört"))

    if not plays and not completed:
        components.append((discovery * 3.0, "Entdeckung"))

    positive = sum(value for value, _ in components)
    score = positive - negative + rng.uniform(0, 0.6 + discovery * 2.5)
    reason = max(components, default=(0.0, "Deine Bibliothek entdecken"))[1]
    return score, reason


def _format_track(row: dict) -> dict:
    duration = int(row.get("duration") or 0)
    minutes, seconds = divmod(duration, 60)
    row["duration_fmt"] = f"{minutes}:{seconds:02d}"
    row["format"] = os.path.splitext(row.get("path") or "")[1].lstrip(".").upper() or "MP3"
    row["has_cover"] = bool(row.get("cover_hash"))
    row["user_play_count"] = int(row.get("user_play_count") or 0)
    for private in (
        "completed_count", "skipped_count", "early_skips", "avg_completion",
        "same_hour_completed", "last_event_at", "in_personal_playlist",
        "signal_strength", "_adolar4u_score",
    ):
        row.pop(private, None)
    return row


def recommend_tracks(user_id: int, count=25, exclude_ids=None, shuffle_state=None,
                     rng=None) -> list[dict] | None:
    """Return a personalized, Smart-Shuffle-ordered Adolar4U queue."""
    global_settings = get_global_settings()
    user_settings = get_user_settings(user_id)
    if not global_settings["enabled"] or not user_settings["enabled"]:
        return None

    count = max(1, min(int(count), 100))
    rng = rng or random
    candidates, stats = _load_candidates(int(user_id), max(2500, count * 100))
    excluded = {int(value) for value in (exclude_ids or [])}
    candidates = [row for row in candidates if int(row["id"]) not in excluded]
    if not candidates:
        return []

    discovery = max(0.0, min(float(user_settings["discovery_level"]), 1.0))
    artist_affinity, genre_affinity = _affinity_maps(candidates)
    now = time.time()
    for row in candidates:
        score, reason = _score_candidate(
            row, artist_affinity, genre_affinity, discovery, rng, now,
        )
        row["_adolar4u_score"] = score
        row["adolar4u_reason"] = reason
    candidates.sort(key=lambda row: row["_adolar4u_score"], reverse=True)

    target = min(len(candidates), max(60, count * 4))
    exploration_count = min(target - 1, round(target * discovery)) if target > 1 else 0
    exploitation_count = target - exploration_count
    shortlist = candidates[:exploitation_count]
    remaining = candidates[exploitation_count:]
    if exploration_count and remaining:
        shortlist.extend(rng.sample(remaining, min(exploration_count, len(remaining))))

    scores = [row["_adolar4u_score"] for row in shortlist]
    high, low = max(scores), min(scores)
    span = high - low or 1.0
    penalties = {
        int(row["id"]): ((high - row["_adolar4u_score"]) / span) * 35.0
        for row in shortlist
    }

    if shuffle_state is None:
        shuffle_state = smart_shuffle.ShuffleState(context=f"adolar4u:{user_id}")
    if shuffle_state.total_tracks is None:
        shuffle_state.total_tracks = int(stats.get("total") or 0)
        shuffle_state.unique_artists = int(stats.get("artists") or 0)
        shuffle_state.unique_albums = int(stats.get("albums") or 0)
        shuffle_state.unique_genres = int(stats.get("genres") or 0)

    selected = smart_shuffle.select_tracks(
        shortlist, count, shuffle_state,
        shuffle_state.total_tracks or len(candidates),
        shuffle_state.unique_artists or 0,
        shuffle_state.unique_albums or 0,
        exclude_ids=excluded,
        rng=rng,
        unique_genres=shuffle_state.unique_genres or 0,
        candidate_penalties=penalties,
    )
    return [_format_track(dict(row)) for row in selected]
