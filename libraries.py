"""Registry of known music libraries (music path + content database per library).

Stored as a small JSON file outside any content database, so it survives
switching which content database is active. The active library's music path
and database path are what app.py assigns to MUSIC_ROOT and db.DB_PATH.
"""

import json
import os
import threading
import uuid

import errors

_LOCK = threading.Lock()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _default_registry(music_root: str, db_path: str) -> dict:
    lib_id = _new_id()
    return {
        "active": lib_id,
        "libraries": [
            {"id": lib_id, "name": "Bibliothek", "music_path": music_root, "db_path": db_path},
        ],
    }


def load_registry(registry_path: str, music_root: str, db_path: str) -> dict:
    """Load the registry, seeding it from the current MUSIC_ROOT/DB_PATH on first run."""
    if not os.path.exists(registry_path):
        registry = _default_registry(music_root, db_path)
        save_registry(registry_path, registry)
        return registry
    with open(registry_path, encoding="utf-8") as f:
        return json.load(f)


def save_registry(registry_path: str, registry: dict) -> None:
    os.makedirs(os.path.dirname(registry_path), exist_ok=True)
    tmp_path = registry_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, registry_path)


def get_active(registry_path: str, music_root: str, db_path: str) -> dict:
    registry = load_registry(registry_path, music_root, db_path)
    for lib in registry["libraries"]:
        if lib["id"] == registry["active"]:
            return lib
    return registry["libraries"][0]


def list_libraries(registry_path: str, music_root: str, db_path: str) -> tuple[list[dict], str]:
    registry = load_registry(registry_path, music_root, db_path)
    return registry["libraries"], registry["active"]


def add_library(
    registry_path: str, music_root: str, db_path: str,
    libraries_dir: str, name: str, new_music_path: str,
) -> dict:
    """Register a new library with a freshly-managed database file and activate it."""
    with _LOCK:
        registry = load_registry(registry_path, music_root, db_path)
        lib_id = _new_id()
        lib = {
            "id": lib_id,
            "name": name,
            "music_path": new_music_path,
            "db_path": os.path.join(libraries_dir, f"{lib_id}.db"),
        }
        registry["libraries"].append(lib)
        registry["active"] = lib_id
        save_registry(registry_path, registry)
        return lib


def set_active(registry_path: str, music_root: str, db_path: str, library_id: str) -> dict:
    with _LOCK:
        registry = load_registry(registry_path, music_root, db_path)
        for lib in registry["libraries"]:
            if lib["id"] == library_id:
                registry["active"] = library_id
                save_registry(registry_path, registry)
                return lib
        raise errors.ValidationError("Unbekannte Bibliothek.")


def update_music_path(
    registry_path: str, music_root: str, db_path: str,
    library_id: str, new_music_path: str,
) -> dict:
    with _LOCK:
        registry = load_registry(registry_path, music_root, db_path)
        for lib in registry["libraries"]:
            if lib["id"] == library_id:
                lib["music_path"] = new_music_path
                save_registry(registry_path, registry)
                return lib
        raise errors.ValidationError("Unbekannte Bibliothek.")
