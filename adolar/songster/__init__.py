"""Adolar Songster integration.

Songster is an external party-game product that draws its song pool from
Adolar via a small, separate API surface (see adolar/routes/songster.py).
This package holds the global on/off switch; the songster_enabled column
on radio_stations (which curated stations are exposed to Songster) lives
in adolar/db.py alongside the rest of the schema.
"""

from .service import get_global_settings, update_global_settings

__all__ = ["get_global_settings", "update_global_settings"]
