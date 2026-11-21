import hashlib
import os
import time

import requests

# A self-hosted Adolar Scrobbler instance this deployment scrobbles to, in
# addition to (or instead of) last.fm. It speaks the same last.fm 2.0 Web
# Service protocol (see adolar/lastfm.py), so this module mirrors it closely,
# but auth happens via auth.getMobileSession (username+password submitted
# directly) rather than last.fm's browser-redirect auth.getSession flow -
# simpler, and appropriate since the instance is admin-trusted, not a
# third-party service. Unlike lastfm.py, there is no loved-tracks/playcount
# sync here: Adolar Scrobbler is a write destination, not a second source of
# truth to read back from.
API_KEY    = os.environ.get("ADOLAR_SCROBBLER_API_KEY", "")
API_SECRET = os.environ.get("ADOLAR_SCROBBLER_API_SECRET", "")
API_ROOT   = os.environ.get("ADOLAR_SCROBBLER_API_ROOT", "")


def configured() -> bool:
    return bool(API_KEY and API_SECRET and API_ROOT)


def _sig(params: dict) -> str:
    """last.fm-style API signature: sorted key+value string, no 'format', + secret, md5."""
    s = "".join(f"{k}{params[k]}" for k in sorted(params) if k != "format")
    s += API_SECRET
    # MD5 is mandated by the last.fm-compatible API signing protocol; this is
    # not used as a security hash selected by the application.
    return hashlib.md5(s.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324


def _post(params: dict) -> dict:
    p = dict(params)          # never mutate caller's dict
    p["api_key"] = API_KEY
    p["format"]  = "json"
    p["api_sig"] = _sig(p)
    r = requests.post(API_ROOT, data=p, timeout=10)
    r.raise_for_status()
    return r.json()


def _get(params: dict) -> dict:
    p = dict(params)
    p["api_key"] = API_KEY
    p["format"] = "json"
    r = requests.get(API_ROOT, params=p, timeout=10)
    r.raise_for_status()
    return r.json()


def get_mobile_session(username: str, password: str) -> dict:
    """Exchange username/password for a session key. Returns {"name": ..., "key": ...}."""
    data = _post({"method": "auth.getMobileSession", "username": username, "password": password})
    return data.get("session", {})


def now_playing(session_key: str, artist: str, title: str, duration: int = None,
                album: str = None, year: int = None) -> dict:
    params = {"method": "track.updateNowPlaying", "sk": session_key,
              "artist": artist, "track": title}
    if duration:
        params["duration"] = duration
    if album:
        params["album"] = album
    if year:
        params["year"] = year
    return _post(params)


def scrobble(session_key: str, artist: str, title: str, timestamp: int = None,
             album: str = None, duration: int = None, year: int = None) -> dict:
    if timestamp is None:
        timestamp = int(time.time())
    params = {
        "method":    "track.scrobble",
        "sk":        session_key,
        "artist":    artist,
        "track":     title,
        "timestamp": timestamp,
    }
    if album:
        params["album"] = album
    if duration:
        params["duration"] = duration
    if year:
        params["year"] = year
    return _post(params)


def get_loved_tracks(username: str, limit: int = 200) -> list[dict]:
    """Fetch all loved tracks from the compatible Adolar Scrobbler API."""
    tracks = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        data = _get({"method": "user.getLovedTracks", "user": username,
                     "limit": limit, "page": page})
        loved = data.get("lovedtracks", {})
        attrs = loved.get("@attr", {})
        total_pages = int(attrs.get("totalPages") or page)
        items = loved.get("track", [])
        if isinstance(items, dict):
            items = [items]
        for item in items:
            artist = item.get("artist", {})
            date = item.get("date", {})
            tracks.append({
                "artist": artist.get("name") if isinstance(artist, dict) else str(artist),
                "title": item.get("name"),
                "loved_at": int(date["uts"]) if isinstance(date, dict) and date.get("uts") else None,
            })
        page += 1
    return tracks


def love(session_key: str, artist: str, title: str) -> dict:
    return _post({"method": "track.love", "sk": session_key,
                  "artist": artist, "track": title})


def unlove(session_key: str, artist: str, title: str) -> dict:
    return _post({"method": "track.unlove", "sk": session_key,
                  "artist": artist, "track": title})
