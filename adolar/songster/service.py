"""Global settings for the Adolar Songster integration.

Mirrors adolar/adolar4u/service.py's global-settings pattern: a single
boolean stored in control.settings, gating both the "Songster" menu entry
(client reads GET /api/songster/status) and every /api/songster/* route.
"""

from __future__ import annotations


def _db_module():
    from .. import db
    return db


def _bool_setting(value) -> bool:
    return str(value or "0") == "1"


def get_global_settings() -> dict:
    db = _db_module()
    return {
        "enabled": _bool_setting(db.get_setting("songster_enabled", "0")),
    }


def update_global_settings(values: dict) -> dict:
    db = _db_module()
    if "enabled" in values:
        db.set_setting("songster_enabled", "1" if bool(values["enabled"]) else "0")
    return get_global_settings()
