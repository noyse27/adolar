"""Lyrics discovery, persistence, synchronization, and provider access."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from mutagen.id3 import ID3, SYLT, USLT, ID3NoHeaderError

import db

log = logging.getLogger(__name__)

MISSING_RETRY_SECONDS = 28 * 24 * 60 * 60
ERROR_RETRY_SECONDS = 12 * 60 * 60
MAX_LYRICS_LENGTH = 500_000
DEFAULT_PROVIDER_URL = "https://lrclib.net"
USER_AGENT = "Adolar/1.7.0 (lyrics; self-hosted music server)"

SETTINGS_DEFAULTS = {
    "lyrics_enabled": "0",
    "lyrics_auto_fetch": "1",
    "lyrics_write_tags": "1",
    "lyrics_write_sidecar": "1",
    "lyrics_overwrite_local": "0",
    "lyrics_provider": "lrclib",
    "lyrics_provider_url": DEFAULT_PROVIDER_URL,
}

_LRC_TIMESTAMP = re.compile(
    r"\[(?P<minutes>\d{1,3}):(?P<seconds>\d{1,2}(?:\.\d{1,3})?)\]"
)
_LRC_METADATA = re.compile(r"^\[(?:ar|al|ti|au|by|offset|re|ve|length):.*\]$", re.I)


class LyricsError(Exception):
    """Base exception for expected lyrics failures.

    Carries a curated, user-facing German message. Read .user_message (not
    str(exc)) when building an API response — same convention as
    errors.ValidationError, kept as a separate hierarchy (not a ValueError
    subclass) so it can't be swallowed by an earlier `except ValueError`.
    """

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class LyricsConflict(LyricsError):
    """The caller attempted to update a stale lyrics revision."""


class LyricsValidationError(LyricsError):
    """The caller supplied malformed or excessively large lyrics."""


@dataclass
class ProviderResult:
    plain: str
    synced: str
    source_id: str | None = None
    instrumental: bool = False


def enabled() -> bool:
    return db.get_setting("lyrics_enabled", SETTINGS_DEFAULTS["lyrics_enabled"]) == "1"


def auto_fetch_enabled() -> bool:
    return db.get_setting(
        "lyrics_auto_fetch", SETTINGS_DEFAULTS["lyrics_auto_fetch"]
    ) == "1"


def get_settings(*, include_secret_state: bool = False) -> dict:
    result = {
        key.removeprefix("lyrics_"): db.get_setting(key, default)
        for key, default in SETTINGS_DEFAULTS.items()
    }
    for key in ("enabled", "auto_fetch", "write_tags", "write_sidecar", "overwrite_local"):
        result[key] = result[key] == "1"
    if include_secret_state:
        result["api_key_configured"] = bool(db.get_setting("lyrics_api_key", ""))
    return result


def update_settings(values: dict) -> dict:
    boolean_keys = {
        "enabled", "auto_fetch", "write_tags", "write_sidecar", "overwrite_local",
    }
    allowed = boolean_keys | {"provider", "provider_url", "api_key"}
    if any(key not in allowed for key in values):
        raise LyricsValidationError("Unbekannte Lyrics-Einstellung.")
    for key in boolean_keys:
        if key in values and not isinstance(values[key], bool):
            raise LyricsValidationError("Lyrics-Schalter müssen boolesch sein.")

    provider = str(
        values.get("provider", db.get_setting("lyrics_provider", "lrclib"))
    ).strip().lower()
    if provider != "lrclib":
        raise LyricsValidationError("Derzeit wird nur LRCLIB unterstützt.")
    provider_url = str(
        values.get("provider_url", db.get_setting("lyrics_provider_url", DEFAULT_PROVIDER_URL))
    ).strip().rstrip("/")
    parsed = urllib.parse.urlparse(provider_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise LyricsValidationError("Ungültige Anbieter-URL.")

    for key in boolean_keys:
        if key in values:
            db.set_setting(f"lyrics_{key}", "1" if values[key] else "0")
    if "provider" in values:
        db.set_setting("lyrics_provider", provider)
    if "provider_url" in values:
        db.set_setting("lyrics_provider_url", provider_url)
    if "api_key" in values:
        db.set_setting("lyrics_api_key", str(values["api_key"] or "").strip())
    return get_settings(include_secret_state=True)


def lrc_to_plain(value: str) -> str:
    lines: list[str] = []
    for raw_line in (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _LRC_METADATA.match(raw_line.strip()):
            continue
        text = _LRC_TIMESTAMP.sub("", raw_line).strip()
        if text or (lines and lines[-1]):
            lines.append(text)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def lrc_lines(value: str) -> list[dict]:
    result: list[dict] = []
    for raw_line in (value or "").splitlines():
        matches = list(_LRC_TIMESTAMP.finditer(raw_line))
        if not matches:
            continue
        text = _LRC_TIMESTAMP.sub("", raw_line).strip()
        for match in matches:
            milliseconds = int(
                (int(match.group("minutes")) * 60 + float(match.group("seconds"))) * 1000
            )
            result.append({"time_ms": milliseconds, "text": text})
    result.sort(key=lambda row: row["time_ms"])
    return result


def _normalize_text(value: str | None) -> str:
    text = str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_LYRICS_LENGTH:
        raise LyricsValidationError("Lyrics sind zu groß.")
    return text.strip()


def _sidecar_paths(audio_path: str) -> tuple[str, str]:
    stem, _ = os.path.splitext(audio_path)
    return stem + ".lrc", stem + ".txt"


def read_sidecar(audio_path: str) -> ProviderResult | None:
    lrc_path, text_path = _sidecar_paths(audio_path)
    for path, synced in ((lrc_path, True), (text_path, False)):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as handle:
                content = _normalize_text(handle.read())
        except (OSError, UnicodeError) as exc:
            log.warning("Could not read lyrics sidecar %s: %s", path, exc)
            continue
        if not content:
            continue
        return ProviderResult(
            plain=lrc_to_plain(content) if synced else content,
            synced=content if synced else "",
        )
    return None


def read_mp3_tags(audio_path: str) -> ProviderResult | None:
    if os.path.splitext(audio_path)[1].lower() != ".mp3":
        return None
    try:
        tags = ID3(audio_path)
    except (ID3NoHeaderError, OSError):
        return None

    synced_frames = tags.getall("SYLT")
    synced = ""
    if synced_frames:
        rows = []
        for text, milliseconds in synced_frames[0].text:
            minutes, remainder = divmod(int(milliseconds), 60_000)
            seconds = remainder / 1000
            rows.append(f"[{minutes:02d}:{seconds:05.2f}]{text}")
        synced = "\n".join(rows).strip()

    plain_frames = tags.getall("USLT")
    plain = _normalize_text(plain_frames[0].text) if plain_frames else ""
    if not plain and synced:
        plain = lrc_to_plain(synced)
    if not plain and not synced:
        return None
    return ProviderResult(plain=plain, synced=synced)


def read_local(audio_path: str) -> tuple[ProviderResult, str] | None:
    sidecar = read_sidecar(audio_path)
    if sidecar:
        return sidecar, "sidecar"
    embedded = read_mp3_tags(audio_path)
    if embedded:
        return embedded, "tag"
    return None


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".adolar-lyrics-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def write_sidecar(audio_path: str, plain: str, synced: str) -> str | None:
    lrc_path, text_path = _sidecar_paths(audio_path)
    target = lrc_path if synced else text_path
    content = synced or plain
    if not content:
        return None
    _atomic_write(target, content)
    return target


def write_mp3_tags(audio_path: str, plain: str, synced: str) -> None:
    if os.path.splitext(audio_path)[1].lower() != ".mp3":
        return
    try:
        tags = ID3(audio_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("USLT")
    tags.delall("SYLT")
    if plain:
        tags.add(USLT(encoding=3, lang="und", desc="Adolar", text=plain))
    timed = lrc_lines(synced)
    if timed:
        tags.add(SYLT(
            encoding=3, lang="und", format=2, type=1, desc="Adolar",
            text=[(row["text"], row["time_ms"]) for row in timed],
        ))
    tags.save(audio_path)


def fetch_lrclib(track: dict, *, timeout: float = 8.0) -> ProviderResult | None:
    settings = get_settings()
    params = {
        "track_name": track.get("title") or "",
        "artist_name": track.get("artist") or "",
        "album_name": track.get("album") or "",
        "duration": int(track.get("duration") or 0),
    }
    if not params["track_name"] or not params["artist_name"]:
        return None
    url = f"{settings['provider_url']}/api/get?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    api_key = db.get_setting("lyrics_api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - URL scheme is validated
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    plain = _normalize_text(payload.get("plainLyrics"))
    synced = _normalize_text(payload.get("syncedLyrics"))
    instrumental = bool(payload.get("instrumental"))
    if not plain and synced:
        plain = lrc_to_plain(synced)
    if not plain and not synced and not instrumental:
        return None
    return ProviderResult(
        plain=plain,
        synced=synced,
        source_id=str(payload.get("id")) if payload.get("id") is not None else None,
        instrumental=instrumental,
    )


def _track(track_id: int) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT id, path, title, artist, album, duration, mtime
               FROM tracks WHERE id=?""",
            (int(track_id),),
        ).fetchone()
    return dict(row) if row else None


def get_track_lyrics(track_id: int) -> dict | None:
    with db.db() as conn:
        row = conn.execute(
            """SELECT l.*, t.title, t.artist, t.album
               FROM track_lyrics l JOIN tracks t ON t.id=l.track_id
               WHERE l.track_id=?""",
            (int(track_id),),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["available"] = result["status"] == "available"
    result["instrumental"] = result["status"] == "instrumental"
    result["lines"] = lrc_lines(result.get("synced_lyrics") or "")
    return result


def _store_result(
    track_id: int,
    result: ProviderResult,
    *,
    source: str,
    source_id: str | None = None,
    sync_state: str = "clean",
) -> dict:
    now = time.time()
    status = "instrumental" if result.instrumental else "available"
    with db.db() as conn:
        conn.execute(
            """INSERT INTO track_lyrics
                   (track_id, status, plain_lyrics, synced_lyrics, format, source,
                    source_id, checked_at, next_check_at, revision, sync_state, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, NULL)
               ON CONFLICT(track_id) DO UPDATE SET
                   status=excluded.status,
                   plain_lyrics=excluded.plain_lyrics,
                   synced_lyrics=excluded.synced_lyrics,
                   format=excluded.format,
                   source=excluded.source,
                   source_id=excluded.source_id,
                   checked_at=excluded.checked_at,
                   next_check_at=NULL,
                   revision=track_lyrics.revision + 1,
                   sync_state=excluded.sync_state,
                   last_error=NULL""",
            (
                int(track_id), status, result.plain, result.synced,
                "lrc" if result.synced else "plain", source,
                source_id or result.source_id, now, sync_state,
            ),
        )
    return get_track_lyrics(track_id)


def mark_missing(track_id: int) -> None:
    now = time.time()
    with db.db() as conn:
        conn.execute(
            """UPDATE track_lyrics
               SET status='missing', checked_at=?, next_check_at=?,
                   last_error=NULL, sync_state='clean'
               WHERE track_id=?""",
            (now, now + MISSING_RETRY_SECONDS, int(track_id)),
        )


def mark_error(track_id: int, error: Exception) -> None:
    now = time.time()
    with db.db() as conn:
        conn.execute(
            """UPDATE track_lyrics
               SET status='error', checked_at=?, next_check_at=?, last_error=?
               WHERE track_id=?""",
            (
                now, now + ERROR_RETRY_SECONDS,
                f"{type(error).__name__}: {str(error)[:300]}", int(track_id),
            ),
        )


def due(track_id: int) -> bool:
    with db.db() as conn:
        row = conn.execute(
            "SELECT status, next_check_at FROM track_lyrics WHERE track_id=?",
            (int(track_id),),
        ).fetchone()
    if row is None or row["status"] == "pending":
        return True
    return (
        row["status"] in ("missing", "error")
        and float(row["next_check_at"] or 0) <= time.time()
    )


def resolve_track(track_id: int, *, force: bool = False) -> dict | None:
    track = _track(track_id)
    if track is None:
        return None
    if not force and not due(track_id):
        return get_track_lyrics(track_id)

    local = read_local(track["path"])
    if local:
        result, source = local
        return _store_result(track_id, result, source=source)

    if not enabled() or not auto_fetch_enabled():
        mark_missing(track_id)
        return get_track_lyrics(track_id)

    try:
        result = fetch_lrclib(track)
        if result is None:
            mark_missing(track_id)
            return get_track_lyrics(track_id)
        stored = _store_result(track_id, result, source="lrclib")
        _sync_files(track, result)
        return stored
    except Exception as exc:
        log.warning("Lyrics lookup failed for track %s: %s", track_id, exc)
        mark_error(track_id, exc)
        return get_track_lyrics(track_id)


def search_provider_candidates(track_id: int, *, timeout: float = 8.0) -> list[dict]:
    """Return sanitized LRCLIB candidates without changing stored lyrics."""
    track = _track(track_id)
    if track is None:
        raise LookupError("track not found")
    params = {
        "track_name": track.get("title") or "",
        "artist_name": track.get("artist") or "",
        "album_name": track.get("album") or "",
    }
    if not params["track_name"]:
        return []
    settings = get_settings()
    url = f"{settings['provider_url']}/api/search?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    api_key = db.get_setting("lyrics_api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        return []
    candidates = []
    for item in payload[:20]:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        candidates.append({
            "id": str(item["id"]),
            "title": str(item.get("trackName") or ""),
            "artist": str(item.get("artistName") or ""),
            "album": str(item.get("albumName") or ""),
            "duration": int(round(float(item.get("duration") or 0))),
            "synced": bool(item.get("syncedLyrics")),
            "instrumental": bool(item.get("instrumental")),
        })
    return candidates


def apply_provider_candidate(
    track_id: int,
    source_id: str,
    *,
    timeout: float = 8.0,
) -> dict:
    """Fetch a selected LRCLIB record by ID and replace the local lyrics."""
    track = _track(track_id)
    if track is None:
        raise LookupError("track not found")
    if not str(source_id).isdigit() or int(source_id) <= 0:
        raise LyricsValidationError("Ungültige Lyrics-Treffer-ID.")
    settings = get_settings()
    url = f"{settings['provider_url']}/api/get/{int(source_id)}"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    api_key = db.get_setting("lyrics_api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    plain = _normalize_text(payload.get("plainLyrics"))
    synced = _normalize_text(payload.get("syncedLyrics"))
    instrumental = bool(payload.get("instrumental"))
    if not plain and synced:
        plain = lrc_to_plain(synced)
    if not plain and not synced and not instrumental:
        raise LyricsValidationError("Der gewählte Treffer enthält keine Lyrics.")
    result = ProviderResult(
        plain=plain,
        synced=synced,
        source_id=str(source_id),
        instrumental=instrumental,
    )
    stored = _store_result(track_id, result, source="lrclib")
    _sync_files(track, result)
    return get_track_lyrics(track_id) or stored


def _sync_files(track: dict, result: ProviderResult) -> str:
    settings = get_settings()
    failures: list[str] = []
    if settings["write_sidecar"]:
        try:
            write_sidecar(track["path"], result.plain, result.synced)
        except OSError as exc:
            failures.append(f"sidecar: {exc}")
    if settings["write_tags"]:
        try:
            write_mp3_tags(track["path"], result.plain, result.synced)
        except Exception as exc:
            failures.append(f"tag: {exc}")
    try:
        mtime = os.stat(track["path"]).st_mtime
        with db.db() as conn:
            conn.execute("UPDATE tracks SET mtime=? WHERE id=?", (mtime, track["id"]))
            conn.execute(
                """UPDATE track_lyrics SET sync_state=?, last_error=?
                   WHERE track_id=?""",
                (
                    "dirty" if failures else "clean",
                    "; ".join(failures)[:500] if failures else None,
                    track["id"],
                ),
            )
    except OSError as exc:
        failures.append(str(exc))
    return "dirty" if failures else "clean"


def update_track_lyrics(
    track_id: int,
    *,
    content: str,
    format_: str,
    expected_revision: int,
    user_id: int,
) -> dict:
    content = _normalize_text(content)
    if format_ not in ("plain", "lrc"):
        raise LyricsValidationError("Unbekanntes Lyrics-Format.")
    if not content:
        raise LyricsValidationError("Lyrics dürfen nicht leer sein.")
    current = get_track_lyrics(track_id)
    if current is None:
        raise LookupError("track not found")
    if int(current["revision"]) != int(expected_revision):
        raise LyricsConflict("Lyrics wurden zwischenzeitlich geändert.")
    plain = lrc_to_plain(content) if format_ == "lrc" else content
    synced = content if format_ == "lrc" else ""
    result = ProviderResult(plain=plain, synced=synced)
    stored = _store_result(
        track_id, result, source="user", source_id=f"user:{int(user_id)}", sync_state="dirty",
    )
    track = _track(track_id)
    if track:
        _sync_files(track, result)
    return get_track_lyrics(track_id) or stored


def ensure_all_rows() -> int:
    with db.db() as conn:
        before = conn.total_changes
        conn.execute(
            """INSERT OR IGNORE INTO track_lyrics (track_id, status)
               SELECT id, 'pending' FROM tracks"""
        )
        return conn.total_changes - before
