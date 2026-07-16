"""Optional, privacy-first personalization module for Adolar."""

from .schema import init_schema
from .service import (
    delete_profile,
    get_global_settings,
    get_user_settings,
    record_event,
    update_global_settings,
    update_user_settings,
)
from .recommender import recommend_tracks

__all__ = [
    "delete_profile",
    "get_global_settings",
    "get_user_settings",
    "init_schema",
    "record_event",
    "recommend_tracks",
    "update_global_settings",
    "update_user_settings",
]
