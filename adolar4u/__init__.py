"""Optional, privacy-first personalization module for Adolar."""

from .export import build_learning_export
from .recommender import recommend_tracks
from .schema import init_schema
from .service import (
    complete_onboarding,
    delete_profile,
    get_global_settings,
    get_learning_history,
    get_onboarding_state,
    get_seed_affinities,
    get_user_settings,
    record_event,
    search_onboarding_options,
    update_global_settings,
    update_user_settings,
)

__all__ = [
    "delete_profile",
    "complete_onboarding",
    "build_learning_export",
    "get_global_settings",
    "get_learning_history",
    "get_onboarding_state",
    "get_seed_affinities",
    "get_user_settings",
    "init_schema",
    "record_event",
    "search_onboarding_options",
    "recommend_tracks",
    "update_global_settings",
    "update_user_settings",
]
