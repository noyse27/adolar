"""Explainable, metadata-first recommendation engine for the Adolar4U MVP."""

from __future__ import annotations

from collections import Counter
import json
import logging
import math
import os
import random
import time
import uuid

import smart_shuffle

from .service import get_global_settings, get_seed_affinities, get_user_settings


ALGORITHM_VERSION = "metadata-v2-skip-smoothing-1"
DIAGNOSTIC_RETENTION_DAYS = 60

# Skip penalties are ratios (skips / events), smoothed with pseudo-observations
# in the denominator. Without smoothing, a single early skip of a barely-heard
# track produced the maximum ratio (1/1) and a combined penalty of -6.5 -- the
# same as a track skipped ten times in a row -- which effectively banned a
# track after one impatient moment. Real-listening validation (July 2026)
# showed this to be too harsh. With SKIP_PENALTY_SMOOTHING pseudo-events, one
# skip is a mild dampener (ratio 1/4) while repeated skips still converge
# toward the full penalty. Do not remove the smoothing without new evidence
# from the learning journal.
SKIP_PENALTY_SMOOTHING = 3.0


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
               CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved,
               t.loved AS library_loved,
               COALESCE(upc.count, 0) AS user_play_count,
               upc.last_played_at,
               COALESCE(ev.completed_count, 0) AS completed_count,
               COALESCE(ev.skipped_count, 0) AS skipped_count,
               COALESCE(ev.early_skips, 0) AS early_skips,
               COALESCE(ev.avg_completion, 0) AS avg_completion,
               COALESCE(ev.same_hour_completed, 0) AS same_hour_completed,
               ev.last_event_at,
               EXISTS(
                   SELECT 1 FROM playlist_tracks favt
                   JOIN playlists fav ON fav.id=favt.playlist_id
                   WHERE favt.track_id=t.id AND fav.owner_id=?
                     AND fav.system_key='favorites'
               ) AS is_favorite,
               EXISTS(
                   SELECT 1 FROM playlist_tracks plt
                   JOIN playlists pl ON pl.id=plt.playlist_id
                   WHERE plt.track_id=t.id AND pl.owner_id=?
                     AND COALESCE(pl.system_key, '') != 'favorites'
               ) AS in_personal_playlist,
               (COALESCE(upc.count, 0) * 2
                + CASE WHEN l.artist_norm IS NOT NULL OR t.loved=1 OR EXISTS(
                    SELECT 1 FROM playlist_tracks favt2
                    JOIN playlists fav2 ON fav2.id=favt2.playlist_id
                    WHERE favt2.track_id=t.id AND fav2.owner_id=?
                      AND fav2.system_key='favorites'
                  ) THEN 2 ELSE 0 END
                + COALESCE(ev.completed_count, 0) * 3
                - COALESCE(ev.early_skips, 0) * 4
                + CASE WHEN EXISTS(
                    SELECT 1 FROM playlist_tracks plt2
                    JOIN playlists pl2 ON pl2.id=plt2.playlist_id
                    WHERE plt2.track_id=t.id AND pl2.owner_id=?
                      AND COALESCE(pl2.system_key, '') != 'favorites'
                  ) THEN 8 ELSE 0 END) AS signal_strength
        FROM tracks t
        LEFT JOIN lastfm_loved_tracks l
               ON l.artist_norm=LOWER(COALESCE(t.artist, ''))
              AND l.title_norm=LOWER(COALESCE(t.title, ''))
              AND l.user_id=?
        LEFT JOIN user_play_counts upc
               ON upc.track_id=t.id AND upc.user_id=?
        LEFT JOIN event_summary ev ON ev.track_id=t.id
        ORDER BY {order_by}
        LIMIT ?
    """


def _load_candidates(user_id: int, limit: int = 2500) -> tuple[list[dict], dict]:
    db = _db_module()
    hour = time.localtime().tm_hour
    params = [hour] + [user_id] * 7
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


def _affinity_maps(candidates: list[dict], user_id: int | None = None) -> tuple[dict[str, float], dict[str, float]]:
    artists: dict[str, float] = {}
    genres: dict[str, float] = {}
    for row in candidates:
        positive = (
            float(row["user_play_count"] or 0)
            + float(row["completed_count"] or 0) * 1.5
            + (3.0 if row["loved"] or row["library_loved"] or row["is_favorite"] else 0.0)
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

    artists = normalize(artists)
    genres = normalize(genres)
    if user_id is not None:
        seed_artists, seed_genres = get_seed_affinities(user_id)
        for key, weight in seed_artists.items():
            artists[key] = max(artists.get(key, 0.0), weight)
        for key, weight in seed_genres.items():
            genres[key] = max(genres.get(key, 0.0), weight)
    return artists, genres


def _latest_played_at(row: dict) -> float | None:
    """Return the newest durable play or Adolar4U event timestamp."""
    timestamps = []
    for value in (row["last_played_at"], row["last_event_at"]):
        if value is not None:
            timestamps.append(float(value))
    return max(timestamps, default=None)


def _recency_penalty(row: dict, now: float) -> float:
    last_played = _latest_played_at(row)
    if last_played is None:
        return 0.0
    age = max(0.0, now - last_played)
    if age < 24 * 3600:
        return 24.0
    if age < 7 * 86400:
        return 5.0
    return 0.0


def _score_candidate(row: dict, artist_affinity: dict, genre_affinity: dict,
                     discovery: float, rng, now: float) -> tuple[float, str]:
    components: list[tuple[float, str, str]] = []
    penalties: dict[str, float] = {}

    def add_component(key: str, value: float, label: str) -> None:
        if value:
            components.append((float(value), label, key))

    plays = int(row["user_play_count"] or 0)
    completed = int(row["completed_count"] or 0)
    skipped = int(row["skipped_count"] or 0)
    early_skips = int(row["early_skips"] or 0)

    if plays:
        add_component("play_count", math.log1p(plays) * 1.35, "Häufig gehört")
    if row["loved"] or row["library_loved"] or row["is_favorite"]:
        add_component("explicit_favorite", 1.5, "Favorit")
    if row["in_personal_playlist"]:
        add_component("personal_playlist", 2.6, "In deinen Playlists")
    if completed:
        add_component(
            "completed_history", min(3.0, math.log1p(completed) * 1.25),
            "Oft vollständig gehört",
        )
    if row["same_hour_completed"]:
        add_component(
            "same_hour", min(1.5, float(row["same_hour_completed"]) * 0.35),
            "Passt zu dieser Tageszeit",
        )

    artist_fit = artist_affinity.get(_key(row["artist"]), 0.0) * 2.2
    genre_fit = genre_affinity.get(_key(row["genre"]), 0.0) * 1.5
    if artist_fit:
        add_component("artist_affinity", artist_fit, "Passender Künstler")
    if genre_fit:
        add_component("genre_affinity", genre_fit, "Passendes Genre")

    event_total = completed + skipped
    if event_total:
        smoothed_total = event_total + SKIP_PENALTY_SMOOTHING
        penalties["early_skip"] = (early_skips / smoothed_total) * 5.0
        penalties["skip_history"] = (skipped / smoothed_total) * 1.5
        add_component(
            "average_completion", float(row["avg_completion"] or 0) * 1.2,
            "Hohe Hördauer",
        )

    last_played = _latest_played_at(row)
    if last_played is not None:
        age = max(0.0, now - last_played)
        recency_penalty = _recency_penalty(row, now)
        if recency_penalty:
            penalties["recency"] = recency_penalty
        if age > 30 * 86400 and (plays or completed):
            add_component("rediscovery", 0.9, "Lange nicht gehört")

    if not plays and not completed:
        add_component("discovery", discovery * 3.0, "Entdeckung")

    positive = sum(value for value, _, _ in components)
    negative = sum(penalties.values())
    random_bonus = rng.uniform(0, 0.6 + discovery * 2.5)
    score = positive - negative + random_bonus
    reason = max(components, default=(0.0, "Deine Bibliothek entdecken", "default"))[1]
    row["_adolar4u_diagnostics"] = {
        "bonuses": {
            key: round(value, 6) for value, _, key in components
        },
        "bonus_labels": {
            key: label for _, label, key in components
        },
        "penalties": {
            key: round(value, 6) for key, value in penalties.items()
        },
        "random_bonus": round(random_bonus, 6),
        "positive_total": round(positive, 6),
        "negative_total": round(negative, 6),
        "score": round(score, 6),
        "facts": {
            "user_play_count": plays,
            "completed_count": completed,
            "skipped_count": skipped,
            "early_skip_count": early_skips,
            "average_completion": round(float(row["avg_completion"] or 0), 6),
            "last_played_at": last_played,
            "hours_since_played": (
                round(max(0.0, now - last_played) / 3600, 2)
                if last_played is not None else None
            ),
            "lastfm_loved": bool(row["loved"]),
            "library_loved": bool(row["library_loved"]),
            "local_favorite": bool(row["is_favorite"]),
            "personal_playlist": bool(row["in_personal_playlist"]),
            "artist_affinity": round(artist_affinity.get(_key(row["artist"]), 0.0), 6),
            "genre_affinity": round(genre_affinity.get(_key(row["genre"]), 0.0), 6),
        },
    }
    return score, reason


def _candidate_bucket(row: dict, artist_affinity: dict, genre_affinity: dict) -> str:
    if row["loved"] or row["library_loved"] or row["is_favorite"]:
        return "anchor"
    if int(row["user_play_count"] or 0) or int(row["completed_count"] or 0) \
            or row["in_personal_playlist"]:
        return "familiar"
    if artist_affinity.get(_key(row["artist"]), 0.0) >= 0.2 \
            or genre_affinity.get(_key(row["genre"]), 0.0) >= 0.35:
        return "similar"
    return "discovery"


def _bucket_targets(count: int, discovery: float,
                    previous: dict[str, int] | None = None) -> dict[str, int]:
    discovery = max(0.0, min(float(discovery), 0.7))
    remaining = 1.0 - 0.15 - discovery
    weights = {
        "anchor": 0.15,
        "similar": remaining * 0.55,
        "familiar": remaining * 0.45,
        "discovery": discovery,
    }
    previous = previous or {}
    total_before = sum(previous.values())
    total_after = total_before + count
    desired = {key: total_after * value for key, value in weights.items()}
    current = {key: int(previous.get(key, 0)) for key in weights}
    targets = {key: 0 for key in weights}
    for _ in range(count):
        key = max(weights, key=lambda item: desired[item] - current[item])
        targets[key] += 1
        current[key] += 1
    return targets


def _choose_bucketed_candidates(candidates: list[dict], count: int,
                                discovery: float,
                                previous: dict[str, int] | None = None) -> list[dict]:
    buckets = {key: [] for key in ("anchor", "similar", "familiar", "discovery")}
    for row in candidates:
        buckets[row["adolar4u_bucket"]].append(row)
    for rows in buckets.values():
        rows.sort(key=lambda row: row["_adolar4u_score"], reverse=True)

    chosen: list[dict] = []
    used: set[int] = set()
    targets = _bucket_targets(count, discovery, previous)
    if (not previous and count and buckets["anchor"]
            and buckets["anchor"][0]["_adolar4u_score"] >= 0
            and targets["anchor"] == 0):
        donor = max(
            (key for key in targets if key != "anchor"),
            key=lambda key: targets[key],
        )
        if targets[donor] > 0:
            targets[donor] -= 1
            targets["anchor"] = 1
    for bucket, target in targets.items():
        for row in buckets[bucket][:target]:
            chosen.append(row)
            used.add(int(row["id"]))

    if len(chosen) < count:
        fallback = sorted(
            (row for row in candidates if int(row["id"]) not in used),
            key=lambda row: row["_adolar4u_score"], reverse=True,
        )
        chosen.extend(fallback[:count - len(chosen)])
    return chosen


def _profile_snapshot(candidates: list[dict], artist_affinity: dict,
                      genre_affinity: dict) -> dict:
    artist_names: dict[str, str] = {}
    genre_names: dict[str, str] = {}
    for row in candidates:
        artist_key = _key(row.get("artist"))
        genre_key = _key(row.get("genre"))
        if artist_key and artist_key not in artist_names:
            artist_names[artist_key] = str(row.get("artist") or artist_key)
        if genre_key and genre_key not in genre_names:
            genre_names[genre_key] = str(row.get("genre") or genre_key)

    def top(values: dict[str, float], labels: dict[str, str]) -> list[dict]:
        return [
            {"name": labels.get(key, key), "weight": round(float(value), 6)}
            for key, value in sorted(
                values.items(), key=lambda item: item[1], reverse=True,
            )[:15]
        ]

    return {
        "artists": top(artist_affinity, artist_names),
        "genres": top(genre_affinity, genre_names),
        "signals": {
            "lastfm_loved_tracks": sum(bool(row["loved"]) for row in candidates),
            "library_loved_tracks": sum(bool(row["library_loved"]) for row in candidates),
            "local_favorites": sum(bool(row["is_favorite"]) for row in candidates),
            "personal_playlist_tracks": sum(
                bool(row["in_personal_playlist"]) for row in candidates
            ),
            "tracks_with_plays": sum(
                int(row["user_play_count"] or 0) > 0 for row in candidates
            ),
            "tracks_with_completed_events": sum(
                int(row["completed_count"] or 0) > 0 for row in candidates
            ),
            "tracks_with_early_skips": sum(
                int(row["early_skips"] or 0) > 0 for row in candidates
            ),
        },
    }


def _record_recommendation_batch(
    user_id: int,
    selected: list[dict],
    *,
    requested_count: int,
    candidate_count: int,
    discovery: float,
    bucket_pool: dict[str, int],
    bucket_target: dict[str, int],
    profile: dict,
    shuffle_session_id: str | None,
) -> None:
    """Persist selected decisions without making logging a playback dependency."""
    if not selected:
        return
    db = _db_module()
    batch_id = uuid.uuid4().hex
    created_at = time.time()
    bucket_selected = dict(Counter(row["adolar4u_bucket"] for row in selected))
    compact_json = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )
    try:
        with db.db() as conn:
            conn.execute(
                """DELETE FROM adolar4u_recommendation_batches
                   WHERE user_id=? AND created_at < ?""",
                (int(user_id), created_at - DIAGNOSTIC_RETENTION_DAYS * 86400),
            )
            conn.execute("""
                INSERT INTO adolar4u_recommendation_batches
                    (id, user_id, shuffle_session_id, algorithm_version,
                     requested_count, candidate_count, discovery_level,
                     bucket_pool_json, bucket_target_json, bucket_selected_json,
                     profile_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch_id, int(user_id), shuffle_session_id, ALGORITHM_VERSION,
                int(requested_count), int(candidate_count), float(discovery),
                compact_json(bucket_pool), compact_json(bucket_target),
                compact_json(bucket_selected), compact_json(profile), created_at,
            ))
            for position, row in enumerate(selected, start=1):
                cur = conn.execute("""
                    INSERT INTO adolar4u_recommendations
                        (batch_id, user_id, track_id, queue_position,
                         candidate_rank, bucket, reason, score,
                         diagnostics_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, int(user_id), int(row["id"]), position,
                    int(row.get("_adolar4u_candidate_rank") or 0),
                    row["adolar4u_bucket"], row["adolar4u_reason"],
                    float(row["_adolar4u_score"]),
                    compact_json(row.get("_adolar4u_diagnostics") or {}),
                    created_at,
                ))
                row["adolar4u_decision_id"] = int(cur.lastrowid)
    except Exception:
        logging.getLogger(__name__).exception(
            "Adolar4U recommendation diagnostics could not be persisted"
        )


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
        "signal_strength", "library_loved", "is_favorite", "_adolar4u_score",
        "_adolar4u_diagnostics", "_adolar4u_candidate_rank",
    ):
        row.pop(private, None)
    return row


def recommend_tracks(user_id: int, count=25, exclude_ids=None, shuffle_state=None,
                     rng=None, recommendation_session_id: str | None = None) -> list[dict] | None:
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
    artist_affinity, genre_affinity = _affinity_maps(candidates, int(user_id))
    now = time.time()
    for row in candidates:
        score, reason = _score_candidate(
            row, artist_affinity, genre_affinity, discovery, rng, now,
        )
        row["_adolar4u_score"] = score
        row["adolar4u_bucket"] = _candidate_bucket(
            row, artist_affinity, genre_affinity,
        )
        row["adolar4u_reason"] = reason
    candidates.sort(key=lambda row: row["_adolar4u_score"], reverse=True)

    if shuffle_state is None:
        shuffle_state = smart_shuffle.ShuffleState(context=f"adolar4u:{user_id}")
    blocked = set(shuffle_state.track_history)
    bucket_candidates = [
        row for row in candidates if int(row["id"]) not in blocked
    ] or candidates
    for rank, row in enumerate(bucket_candidates, start=1):
        row["_adolar4u_candidate_rank"] = rank
    shortlist = _choose_bucketed_candidates(
        bucket_candidates, count, discovery, shuffle_state.adolar4u_bucket_counts,
    )
    bucket_pool = dict(Counter(row["adolar4u_bucket"] for row in bucket_candidates))
    bucket_target = dict(Counter(row["adolar4u_bucket"] for row in shortlist))
    for row in shortlist:
        bucket = row["adolar4u_bucket"]
        shuffle_state.adolar4u_bucket_counts[bucket] = (
            shuffle_state.adolar4u_bucket_counts.get(bucket, 0) + 1
        )

    scores = [row["_adolar4u_score"] for row in shortlist]
    high, low = max(scores), min(scores)
    span = high - low or 1.0
    penalties = {
        int(row["id"]): ((high - row["_adolar4u_score"]) / span) * 35.0
        for row in shortlist
    }

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
    if not user_settings["learning_paused"]:
        _record_recommendation_batch(
            int(user_id), selected,
            requested_count=count,
            candidate_count=len(bucket_candidates),
            discovery=discovery,
            bucket_pool=bucket_pool,
            bucket_target=bucket_target,
            profile=_profile_snapshot(candidates, artist_affinity, genre_affinity),
            shuffle_session_id=recommendation_session_id,
        )
    return [_format_track(dict(row)) for row in selected]
