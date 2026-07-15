"""Stateful smart shuffle with track, artist, album, and BPM spacing."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import secrets
import threading
import time


SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_SESSIONS = 256


def _key(value) -> str:
    return str(value or "").strip().casefold()


def _album_key(row) -> str:
    album = _key(row["album"])
    if not album:
        return ""
    return f"{_key(row['artist'])}\x1f{album}"


def _bpm(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 and math.isfinite(result) else None


@dataclass
class ShuffleState:
    context: str
    track_history: list[int] = field(default_factory=list)
    artist_last_seen: dict[str, int] = field(default_factory=dict)
    album_last_seen: dict[str, int] = field(default_factory=dict)
    sequence_index: int = 0
    last_bpm: float | None = None
    total_tracks: int | None = None
    unique_artists: int | None = None
    unique_albums: int | None = None
    touched_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset(self, context: str) -> None:
        self.context = context
        self.track_history.clear()
        self.artist_last_seen.clear()
        self.album_last_seen.clear()
        self.sequence_index = 0
        self.last_bpm = None
        self.total_tracks = None
        self.unique_artists = None
        self.unique_albums = None


_sessions: dict[str, ShuffleState] = {}
_sessions_lock = threading.Lock()


def get_session(token: str | None, context: str) -> tuple[str, ShuffleState]:
    """Return a process-local shuffle session, creating or resetting as needed."""
    now = time.time()
    with _sessions_lock:
        expired = [
            key for key, state in _sessions.items()
            if now - state.touched_at > SESSION_TTL_SECONDS
        ]
        for key in expired:
            _sessions.pop(key, None)

        state = _sessions.get(token or "")
        if state is None:
            token = secrets.token_urlsafe(18)
            state = ShuffleState(context=context)
            _sessions[token] = state
        elif state.context != context:
            state.reset(context)
        state.touched_at = now

        if len(_sessions) > MAX_SESSIONS:
            oldest = min(_sessions, key=lambda key: _sessions[key].touched_at)
            if oldest != token:
                _sessions.pop(oldest, None)
        return token, state


def cooldown_windows(total: int, artists: int, albums: int) -> tuple[int, int, int]:
    total = max(0, int(total))
    artists = max(0, int(artists))
    albums = max(0, int(albums))
    return (
        max(1, math.floor(total * 0.8)),
        max(0, min(math.floor(total * 0.2), math.floor((artists - 1) * 0.8))),
        max(0, min(math.floor(total * 0.1), math.floor((albums - 1) * 0.8))),
    )


def bpm_penalty(last_bpm, candidate_bpm) -> float:
    last = _bpm(last_bpm)
    candidate = _bpm(candidate_bpm)
    if last is None or candidate is None:
        return 0.0
    delta = abs(last - candidate)
    if delta <= 5:
        return 0.0
    if delta <= 20:
        return (delta - 5) * 2.5
    return 37.5 + (delta - 20) * 6.0


def _history_penalty(
    value: str,
    last_seen: dict[str, int],
    sequence_index: int,
    window: int,
    maximum: float,
) -> float:
    if not value or window <= 0:
        return 0.0
    previous = last_seen.get(value)
    if previous is None:
        return 0.0
    distance = sequence_index - previous + 1
    if distance > window:
        return 0.0
    return ((window - distance + 1) / window) * maximum


def select_tracks(
    candidates,
    count: int,
    state: ShuffleState,
    total_tracks: int,
    unique_artists: int,
    unique_albums: int,
    exclude_ids=None,
    rng=None,
) -> list:
    """Order up to count candidates and update state for the planned play order."""
    count = max(0, int(count))
    rng = rng or random
    w_track, w_artist, w_album = cooldown_windows(
        total_tracks, unique_artists, unique_albums
    )
    state.track_history = state.track_history[-w_track:]
    if w_artist:
        artist_cutoff = state.sequence_index - w_artist + 1
        state.artist_last_seen = {
            key: position for key, position in state.artist_last_seen.items()
            if position >= artist_cutoff
        }
    else:
        state.artist_last_seen.clear()
    if w_album:
        album_cutoff = state.sequence_index - w_album + 1
        state.album_last_seen = {
            key: position for key, position in state.album_last_seen.items()
            if position >= album_cutoff
        }
    else:
        state.album_last_seen.clear()

    blocked = set(state.track_history)
    explicit_excludes = {int(value) for value in (exclude_ids or [])}
    blocked.update(explicit_excludes)
    remaining = [row for row in candidates if int(row["id"]) not in blocked]
    if not remaining and candidates:
        state.track_history.clear()
        remaining = [
            row for row in candidates
            if int(row["id"]) not in explicit_excludes
        ]

    selected = []
    while remaining and len(selected) < count:
        best_index = 0
        best_score = float("inf")
        for index, row in enumerate(remaining):
            artist = _key(row["artist"])
            album = _album_key(row)
            score = (
                _history_penalty(
                    artist, state.artist_last_seen, state.sequence_index,
                    w_artist, 150.0,
                )
                + _history_penalty(
                    album, state.album_last_seen, state.sequence_index,
                    w_album, 75.0,
                )
                + bpm_penalty(state.last_bpm, row["bpm"])
                + rng.uniform(0, 15)
            )
            if score < best_score:
                best_score = score
                best_index = index

        chosen = remaining.pop(best_index)
        selected.append(chosen)
        state.track_history.append(int(chosen["id"]))
        artist = _key(chosen["artist"])
        album = _album_key(chosen)
        state.sequence_index += 1
        if artist:
            state.artist_last_seen[artist] = state.sequence_index
        if album:
            state.album_last_seen[album] = state.sequence_index
        chosen_bpm = _bpm(chosen["bpm"])
        state.last_bpm = chosen_bpm

        state.track_history = state.track_history[-w_track:]

    state.touched_at = time.time()
    return selected
