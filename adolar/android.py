"""Adolar Mobile backend: track matching and idempotent Android event batches.

Orchestrates existing functionality rather than duplicating it:
adolar4u.record_event() already has its own client_event_id idempotency,
db.record_user_play() already handles the archive/personal playcount split,
and lastfm.scrobble() already accepts an explicit timestamp. See the
Priority-2 plan for the full design rationale.
"""
import time

from . import adolar4u, db, errors, lastfm
from .application import _submit_lastfm_call

MAX_BATCH_SIZE = 200
DURATION_TOLERANCE_SECONDS = 3
EVENT_TYPES = {"started", "skipped", "completed"}


def _norm(text) -> str:
    return (text or "").strip().lower()


def _require_text(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise errors.ValidationError(f"Feld '{field}' darf nicht leer sein.")
    return text


def _optional_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def match_track(
    user_id: int, local_track_id: str, artist: str, title: str,
    album: str = "", duration_seconds=None,
) -> dict:
    """Resolve a local Android track to a server track id.

    Order: a previously confirmed link wins outright; otherwise a
    normalized artist+title lookup, narrowed by album and a duration
    tolerance when more than one candidate matches. The result (including
    ambiguous/unmatched outcomes) is cached in android_track_links so a
    confirmed match is never re-derived, while ambiguous/unmatched rows are
    retried on every call — self-healing once the server library changes.
    """
    local_track_id = str(local_track_id)
    with db.db() as conn:
        cached = conn.execute(
            "SELECT track_id, match_kind, confidence FROM android_track_links "
            "WHERE user_id=? AND local_track_id=?",
            (user_id, local_track_id)
        ).fetchone()
        if cached and cached["match_kind"] == "matched":
            return {
                "local_track_id": local_track_id, "status": "matched",
                "track_id": cached["track_id"], "confidence": cached["confidence"],
            }

        candidates = conn.execute(
            "SELECT id, album, duration FROM tracks "
            "WHERE LOWER(artist)=? AND LOWER(title)=?",
            (_norm(artist), _norm(title))
        ).fetchall()

        status, track_id, confidence = "unmatched", None, None
        if len(candidates) == 1:
            status, track_id, confidence = "matched", candidates[0]["id"], "artist_title"
        elif len(candidates) > 1:
            narrowed = candidates
            if album:
                by_album = [c for c in narrowed if _norm(c["album"]) == _norm(album)]
                if by_album:
                    narrowed = by_album
            duration = _optional_number(duration_seconds)
            if duration and len(narrowed) > 1:
                by_duration = [
                    c for c in narrowed if c["duration"] is not None
                    and abs(float(c["duration"]) - duration) <= DURATION_TOLERANCE_SECONDS
                ]
                if by_duration:
                    narrowed = by_duration
            if len(narrowed) == 1:
                status, track_id, confidence = "matched", narrowed[0]["id"], "normalized_metadata"
            else:
                status = "ambiguous"

        conn.execute(
            """INSERT INTO android_track_links
                   (user_id, local_track_id, track_id, match_kind, confidence,
                    created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id, local_track_id) DO UPDATE SET
                   track_id=excluded.track_id, match_kind=excluded.match_kind,
                   confidence=excluded.confidence, updated_at=excluded.updated_at""",
            (user_id, local_track_id, track_id, status, confidence, time.time(), time.time())
        )
    return {
        "local_track_id": local_track_id, "status": status,
        "track_id": track_id, "confidence": confidence,
    }


def match_tracks(user_id: int, tracks: list[dict]) -> list[dict]:
    if len(tracks) > MAX_BATCH_SIZE:
        raise errors.ValidationError(
            f"Zu viele Titel in einem Batch (maximal {MAX_BATCH_SIZE}).")
    results = []
    for item in tracks:
        local_track_id = _require_text(item.get("local_track_id"), "local_track_id")
        artist = _require_text(item.get("artist"), "artist")
        title = _require_text(item.get("title"), "title")
        results.append(match_track(
            user_id, local_track_id, artist, title,
            item.get("album") or "", item.get("duration_seconds"),
        ))
    return results


def _apply_matched_event(user: dict, track_id: int, event: dict):
    event_type = event["event_type"]
    adolar4u.record_event(user["id"], track_id, {
        "event_type": event_type,
        "source": "android_local",
        "reason": event.get("reason"),
        "position_seconds": event.get("position_seconds"),
        "duration_seconds": event.get("duration_seconds"),
        "client_event_id": event["event_id"],
    })
    if event_type not in ("completed", "skipped"):
        return
    if event.get("playcount_eligible"):
        db.record_user_play(
            user["id"], track_id, bool(user.get("contributes_playcount")),
            record_personal=True,
        )
    if event.get("scrobble_eligible"):
        account = db.get_lastfm_account(user["id"])
        if account:
            started_at = event.get("started_at")
            timestamp = int(started_at) if started_at else None
            _submit_lastfm_call(
                "android-scrobble", lastfm.scrobble, account["session_key"],
                event["artist"], event["title"], timestamp=timestamp, retries=1,
            )


def _validate_event(event: dict) -> dict:
    event_id = _require_text(event.get("event_id"), "event_id")
    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type not in EVENT_TYPES:
        raise errors.ValidationError(
            "Unbekannter Ereignistyp (erwartet: started, skipped oder completed).")
    local_track_id = _require_text(event.get("local_track_id"), "local_track_id")
    artist = _require_text(event.get("artist"), "artist")
    title = _require_text(event.get("title"), "title")
    return {
        **event, "event_id": event_id, "event_type": event_type,
        "local_track_id": local_track_id, "artist": artist, "title": title,
    }


def apply_event_batch(user: dict, device_id: int, events: list[dict]) -> list[dict]:
    if len(events) > MAX_BATCH_SIZE:
        raise errors.ValidationError(
            f"Zu viele Ereignisse in einem Batch (maximal {MAX_BATCH_SIZE}).")
    results = []
    for raw_event in events:
        event = _validate_event(raw_event)
        with db.db() as conn:
            receipt = conn.execute(
                "INSERT OR IGNORE INTO android_event_receipts "
                "(user_id, device_id, event_id, event_type, local_track_id, status) "
                "VALUES (?,?,?,?,?,'pending')",
                (user["id"], device_id, event["event_id"], event["event_type"],
                 event["local_track_id"])
            )
        if receipt.rowcount == 0:
            results.append({"event_id": event["event_id"], "status": "duplicate"})
            continue

        match = match_track(
            user["id"], event["local_track_id"], event["artist"], event["title"],
            event.get("album") or "", event.get("duration_seconds"),
        )
        status = match["status"]
        if status == "matched":
            _apply_matched_event(user, match["track_id"], event)
            status = "applied"
        with db.db() as conn:
            conn.execute(
                "UPDATE android_event_receipts SET status=?, track_id=? "
                "WHERE user_id=? AND device_id=? AND event_id=?",
                (status, match["track_id"], user["id"], device_id, event["event_id"])
            )
        results.append({"event_id": event["event_id"], "status": status})
    return results
