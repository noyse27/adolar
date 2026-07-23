"""Consistent, portable backups for Adolar's SQLite data.

Backups are written as self-contained directories.  A completed directory is
only made visible after SQLite's online backup API and the integrity check have
both succeeded, so interrupted jobs never look like valid backups.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path


BACKUP_ID_RE = re.compile(r"^adolar-\d{8}-\d{6}$")
LOCK_NAME = ".adolar-backup.lock"
STATUS_NAME = ".adolar-backup-status.json"


class BackupError(RuntimeError):
    pass


class BackupInProgress(BackupError):
    pass


def _process_start_token(pid: int) -> str | None:
    if os.name != "posix":
        return None
    try:
        # Linux /proc stat field 22 is the process start time in clock ticks.
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    except (OSError, IndexError):
        return None


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_backup_dir(root: Path, backup_id: str) -> Path:
    if not BACKUP_ID_RE.fullmatch(backup_id):
        raise FileNotFoundError(backup_id)
    candidate = root / backup_id
    root_real = root.resolve()
    candidate_real = candidate.resolve()
    if candidate_real.parent != root_real or candidate.is_symlink():
        raise FileNotFoundError(backup_id)
    return candidate


def ensure_backup_root(root: str) -> Path:
    path = Path(root).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".adolar-write-test"
    try:
        probe.write_bytes(b"")
    finally:
        probe.unlink(missing_ok=True)
    return path


def _lock_is_active(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    try:
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        lock_pid = int(lock_data.get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # Another process may be between creating and filling the lock file.
        return age <= 60
    if lock_pid <= 0 or age > 24 * 60 * 60:
        return False
    if os.name != "posix":
        return True
    expected_start = lock_data.get("process_start")
    if expected_start and _process_start_token(lock_pid) != expected_start:
        return False
    try:
        os.kill(lock_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _acquire_lock(root: Path, source: str) -> int:
    lock_path = root / LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        # A force-killed container can leave the marker behind.  Do not clear a
        # fresh marker: a large NAS database can legitimately need some time.
        if _lock_is_active(lock_path):
            raise BackupInProgress("Eine Datensicherung läuft bereits.") from exc
        lock_path.unlink(missing_ok=True)
        return _acquire_lock(root, source)
    payload = json.dumps({
        "pid": os.getpid(),
        "process_start": _process_start_token(os.getpid()),
        "source": source,
        "started_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }).encode("utf-8")
    os.write(fd, payload)
    os.fsync(fd)
    return fd


def _release_lock(root: Path, fd: int) -> None:
    os.close(fd)
    (root / LOCK_NAME).unlink(missing_ok=True)


def read_status(root: str) -> dict:
    path = Path(root).expanduser().resolve() / STATUS_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"state": "idle"}
    except (OSError, ValueError):
        return {"state": "idle"}


def is_backup_running(root: str) -> bool:
    lock_path = Path(root).expanduser().resolve() / LOCK_NAME
    return _lock_is_active(lock_path)


def _database_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    wanted = (
        "tracks", "users", "playlists", "radio_stations",
        "user_play_counts", "lastfm_loved_tracks",
        "adolar4u_recommendations", "adolar4u_listening_events",
    )
    return {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in wanted if table in tables
    }


def _archive_jingles(jingle_root: str | None, destination: Path) -> tuple[int, int]:
    if not jingle_root:
        return 0, 0
    root = Path(jingle_root)
    files = [
        path for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    ] if root.is_dir() else []
    if not files:
        return 0, 0
    with tarfile.open(destination, "w:gz", compresslevel=1) as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(root), recursive=False)
    return len(files), destination.stat().st_size


def create_backup(
    database_path: str,
    backup_root: str,
    *,
    jingle_root: str | None = None,
    app_version: str = "unknown",
    source: str = "manual",
    retention: int = 7,
) -> dict:
    if not Path(database_path).is_file():
        raise BackupError(f"Datenbank nicht gefunden: {database_path}")
    root = ensure_backup_root(backup_root)
    lock_fd = _acquire_lock(root, source)
    started = dt.datetime.now().astimezone()
    backup_id = started.strftime("adolar-%Y%m%d-%H%M%S")
    partial = root / f".{backup_id}.partial"
    final = root / backup_id
    status_path = root / STATUS_NAME
    try:
        if final.exists():
            raise BackupError("Für diese Sekunde existiert bereits eine Sicherung.")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(mode=0o700)
        _atomic_json(status_path, {
            "state": "running", "source": source,
            "started_at": started.isoformat(timespec="seconds"),
        })

        database_file = partial / "adolar.db"
        source_conn = sqlite3.connect(database_path, timeout=30)
        target_conn = sqlite3.connect(database_file)
        try:
            source_conn.execute("PRAGMA busy_timeout=30000")
            source_conn.backup(target_conn, pages=4096, sleep=0.05)
            result = target_conn.execute("PRAGMA quick_check").fetchone()[0]
            if result != "ok":
                raise BackupError(f"SQLite-Prüfung fehlgeschlagen: {result}")
            counts = _database_counts(target_conn)
        finally:
            target_conn.close()
            source_conn.close()

        jingle_file = partial / "radio-jingles.tar.gz"
        jingle_count, jingle_size = _archive_jingles(jingle_root, jingle_file)
        database_size = database_file.stat().st_size
        manifest = {
            "format_version": 1,
            "backup_id": backup_id,
            "created_at": started.isoformat(timespec="seconds"),
            "source": source,
            "app_version": app_version,
            "database": {
                "file": "adolar.db",
                "size": database_size,
                "sha256": _sha256(database_file),
                "quick_check": "ok",
            },
            "counts": counts,
            "radio_jingles": {
                "file": "radio-jingles.tar.gz" if jingle_count else None,
                "count": jingle_count,
                "size": jingle_size,
            },
        }
        _atomic_json(partial / "manifest.json", manifest)
        os.replace(partial, final)
        removed = prune_backups(str(root), retention, exclude={backup_id})
        completed = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_json(status_path, {
            "state": "completed", "backup_id": backup_id,
            "source": source, "completed_at": completed,
        })
        manifest["removed_by_retention"] = removed
        return manifest
    except Exception as exc:
        shutil.rmtree(partial, ignore_errors=True)
        _atomic_json(status_path, {
            "state": "failed", "source": source,
            "failed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "error": str(exc),
        })
        raise
    finally:
        _release_lock(root, lock_fd)


def list_backups(backup_root: str) -> list[dict]:
    root = ensure_backup_root(backup_root)
    backups = []
    for directory in root.iterdir():
        if not directory.is_dir() or not BACKUP_ID_RE.fullmatch(directory.name):
            continue
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            db_file = _safe_file(root, directory.name, "adolar.db")
            manifest["backup_id"] = directory.name
            manifest["size"] = db_file.stat().st_size
            backups.append(manifest)
        except (OSError, ValueError, KeyError, FileNotFoundError):
            continue
    return sorted(backups, key=lambda item: item.get("created_at", ""), reverse=True)


def prune_backups(backup_root: str, retention: int, exclude: set[str] | None = None) -> list[str]:
    keep = max(1, int(retention))
    exclude = exclude or set()
    backups = list_backups(backup_root)
    removable = [item for item in backups if item.get("backup_id") not in exclude]
    # Excluded (usually the newly created snapshot) also consumes a keep slot.
    allowed_removable = max(0, keep - len(exclude))
    removed = []
    for item in removable[allowed_removable:]:
        backup_id = item.get("backup_id", "")
        try:
            delete_backup(backup_root, backup_id)
            removed.append(backup_id)
        except FileNotFoundError:
            pass
    return removed


def _safe_file(root: Path, backup_id: str, filename: str) -> Path:
    directory = _safe_backup_dir(root, backup_id)
    path = directory / filename
    resolved = path.resolve()
    if resolved.parent != directory.resolve() or path.is_symlink() or not path.is_file():
        raise FileNotFoundError(filename)
    return path


def get_backup_file(backup_root: str, backup_id: str, kind: str = "database") -> Path:
    root = Path(backup_root).expanduser().resolve()
    filenames = {
        "database": "adolar.db",
        "jingles": "radio-jingles.tar.gz",
        "manifest": "manifest.json",
    }
    if kind not in filenames:
        raise FileNotFoundError(kind)
    return _safe_file(root, backup_id, filenames[kind])


def delete_backup(backup_root: str, backup_id: str) -> None:
    root = Path(backup_root).expanduser().resolve()
    directory = _safe_backup_dir(root, backup_id)
    if not directory.is_dir():
        raise FileNotFoundError(backup_id)
    shutil.rmtree(directory)
