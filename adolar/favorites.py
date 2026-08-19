"""Shared favorite/Last.fm-love logic, used by both the web UI and the
Android event batch (adolar/android.py) so the two clients stay unified
rather than growing their own copies of the auto-love rule.
"""
import logging

from . import db, lastfm


def set_user_favorite(user_id: int, track_id: int, favorite: bool) -> tuple[dict, int]:
    """Set the Adolar favorite and mirror it to Last.fm love/unlove when
    the user has auto_love_favorites enabled. Symmetric: unfavoriting
    unloves just like favoriting loves.
    """
    with db.db() as conn:
        track = conn.execute(
            "SELECT id, artist, title FROM tracks WHERE id=?", (int(track_id),)
        ).fetchone()
    if not track:
        return {"error": "track not found"}, 404
    db.set_favorite(user_id, track_id, favorite)
    result = {"ok": True, "favorite": bool(favorite), "lastfm_synced": False}
    account = db.get_lastfm_account(user_id)
    if account and account["auto_love_favorites"]:
        try:
            if favorite:
                lastfm.love(account["session_key"], track["artist"] or "", track["title"] or "")
            else:
                lastfm.unlove(account["session_key"], track["artist"] or "", track["title"] or "")
            db.set_lastfm_loved(user_id, track["artist"], track["title"], favorite)
            result["lastfm_synced"] = True
        except Exception:
            logging.getLogger(__name__).exception("Favorite saved but Last.fm sync failed")
            result["lastfm_error"] = "Last.fm konnte nicht aktualisiert werden."
    return result, 200
