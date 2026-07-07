import os
import hashlib
import time
import requests

API_KEY    = os.environ.get("LASTFM_API_KEY", "")
API_SECRET = os.environ.get("LASTFM_API_SECRET", "")
API_ROOT   = "https://ws.audioscrobbler.com/2.0/"


def _sig(params: dict) -> str:
    """Last.fm API signature: sorted key+value string, no 'format', + secret, md5."""
    s = "".join(f"{k}{params[k]}" for k in sorted(params) if k != "format")
    s += API_SECRET
    # MD5 is mandated by the Last.fm API signing protocol — not a choice
    return hashlib.md5(s.encode("utf-8")).hexdigest()  # noqa: S324


def _post(params: dict) -> dict:
    p = dict(params)          # never mutate caller's dict
    p["api_key"] = API_KEY
    p["format"]  = "json"
    p["api_sig"] = _sig(p)
    r = requests.post(API_ROOT, data=p, timeout=10)
    r.raise_for_status()
    return r.json()


def _get(params: dict) -> dict:
    p = dict(params)          # never mutate caller's dict
    p["api_key"] = API_KEY
    p["format"]  = "json"
    r = requests.get(API_ROOT, params=p, timeout=10)
    r.raise_for_status()
    return r.json()


def get_auth_url(callback_url: str) -> str:
    return (f"https://www.last.fm/api/auth/"
            f"?api_key={API_KEY}&cb={requests.utils.quote(callback_url, safe='')}")


def get_session(token: str) -> dict:
    """Exchange token for session key. Returns {"name": ..., "key": ...}."""
    data = _post({"method": "auth.getSession", "token": token})
    return data.get("session", {})


def now_playing(session_key: str, artist: str, title: str, duration: int = None) -> dict:
    params = {"method": "track.updateNowPlaying", "sk": session_key,
              "artist": artist, "track": title}
    if duration:
        params["duration"] = duration
    return _post(params)


def scrobble(session_key: str, artist: str, title: str, timestamp: int = None) -> dict:
    if timestamp is None:
        timestamp = int(time.time())
    return _post({
        "method":    "track.scrobble",
        "sk":        session_key,
        "artist":    artist,
        "track":     title,
        "timestamp": timestamp,
    })


def love(session_key: str, artist: str, title: str) -> dict:
    return _post({"method": "track.love", "sk": session_key,
                  "artist": artist, "track": title})


def unlove(session_key: str, artist: str, title: str) -> dict:
    return _post({"method": "track.unlove", "sk": session_key,
                  "artist": artist, "track": title})


def get_track_info(session_key: str, artist: str, title: str) -> dict:
    """Returns track info including userloved (0 or 1) and userplaycount."""
    try:
        data = _get({"method": "track.getInfo", "sk": session_key,
                     "artist": artist, "track": title, "username": ""})
        return data.get("track", {})
    except Exception:
        return {}


def get_user_track_playcount(username: str, artist: str, title: str) -> int | None:
    """Fetch userplaycount for a single track. Returns None on error."""
    try:
        data = _get({"method": "track.getInfo", "api_key": API_KEY,
                     "artist": artist, "track": title, "username": username})
        track = data.get("track", {})
        raw = track.get("userplaycount")
        return int(raw) if raw is not None else None
    except Exception:
        return None


def get_loved_tracks(username: str, limit: int = 200) -> list[dict]:
    """Fetch all loved tracks for a Last.fm user."""
    tracks = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        data = _get({
            "method": "user.getLovedTracks",
            "user": username,
            "limit": limit,
            "page": page,
        })
        loved = data.get("lovedtracks", {})
        attrs = loved.get("@attr", {})
        try:
            total_pages = int(attrs.get("totalPages") or total_pages)
        except (TypeError, ValueError):
            total_pages = page

        for item in loved.get("track", []):
            artist = item.get("artist", {})
            if isinstance(artist, dict):
                artist_name = artist.get("name")
            else:
                artist_name = str(artist) if artist else None
            loved_at = None
            date = item.get("date", {})
            if isinstance(date, dict):
                try:
                    loved_at = int(date.get("uts")) if date.get("uts") else None
                except (TypeError, ValueError):
                    loved_at = None
            tracks.append({
                "artist": artist_name,
                "title": item.get("name"),
                "loved_at": loved_at,
            })
        page += 1
    return tracks
