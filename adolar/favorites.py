"""Shared favorite/Last.fm/Adolar-Scrobbler-love logic, used by both the web
UI and the Android event batch (adolar/android.py) so the clients stay
unified rather than growing their own copies of the auto-love rule.
"""
import logging

from . import adolar_scrobbler, db, lastfm


def set_user_favorite(user_id: int, track_id: int, favorite: bool) -> tuple[dict, int]:
    """Set the Adolar favorite and mirror it to Last.fm/Adolar Scrobbler
    love/unlove when the user has auto_love_favorites enabled for whichever
    one is connected (the two are mutually exclusive - see
    routes/lastfm.py's callback and routes/adolar_scrobbler.py's connect
    endpoint). Symmetric: unfavoriting unloves just like favoriting loves.
    """
    with db.db() as conn:
        track = conn.execute(
            "SELECT id, artist, title FROM tracks WHERE id=?", (int(track_id),)
        ).fetchone()
    if not track:
        return {"error": "track not found"}, 404
    db.set_favorite(user_id, track_id, favorite)
    result = {"ok": True, "favorite": bool(favorite), "lastfm_synced": False}
    artist, title = track["artist"] or "", track["title"] or ""

    account = db.get_lastfm_account(user_id)
    if account and account["auto_love_favorites"]:
        try:
            if favorite:
                lastfm.love(account["session_key"], artist, title)
            else:
                lastfm.unlove(account["session_key"], artist, title)
            db.set_lastfm_loved(user_id, track["artist"], track["title"], favorite)
            result["lastfm_synced"] = True
        except Exception:
            logging.getLogger(__name__).exception("Favorite saved but Last.fm sync failed")
            result["lastfm_error"] = "Last.fm konnte nicht aktualisiert werden."

    asb_account = db.get_adolar_scrobbler_account(user_id)
    if asb_account and asb_account["auto_love_favorites"]:
        try:
            if favorite:
                adolar_scrobbler.love(asb_account["session_key"], artist, title)
            else:
                adolar_scrobbler.unlove(asb_account["session_key"], artist, title)
            result["adolar_scrobbler_synced"] = True
        except Exception:
            logging.getLogger(__name__).exception("Favorite saved but Adolar Scrobbler sync failed")
            result["adolar_scrobbler_error"] = "Adolar Scrobbler konnte nicht aktualisiert werden."

    return result, 200
