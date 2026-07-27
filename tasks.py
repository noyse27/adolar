"""Registry for ad-hoc background jobs (library scan, BPM analysis, cover
thumbnail generation, database optimize) so the admin System Monitor can show
what's currently running and what ran recently.

Database backups already track their own status/history in backup_service.py
(file-based, so the separate scheduler thread and a future standalone backup
process would both see it) — that isn't duplicated here. app.py's monitor
endpoint merges both sources into one "tasks" view instead.
"""

import itertools
import logging
import threading
import time

import db

log = logging.getLogger(__name__)

_lock = threading.Lock()
_id_seq = itertools.count(1)
_running: dict[int, dict] = {}

HISTORY_LIMIT = 30


def start(task_type: str, trigger: str = "manual") -> int:
    """Register a job as running. Returns a task_id for update()/finish()."""
    task_id = next(_id_seq)
    with _lock:
        _running[task_id] = {
            "task_type": task_type,
            "trigger": trigger,
            "started_at": time.time(),
            "current": None,
            "total": None,
            "detail": None,
        }
    return task_id


def update(task_id: int, current: int | None = None, total: int | None = None,
           detail: str | None = None) -> None:
    with _lock:
        task = _running.get(task_id)
        if not task:
            return
        if current is not None:
            task["current"] = current
        if total is not None:
            task["total"] = total
        if detail is not None:
            task["detail"] = detail


def finish(task_id: int, status: str = "completed", detail: str | None = None) -> None:
    """Move a task from "running" into the persisted history. status is one
    of "completed", "failed", "aborted"."""
    with _lock:
        task = _running.pop(task_id, None)
    if not task:
        return
    if detail is not None:
        task["detail"] = detail
    try:
        with db.db() as conn:
            # Column is "trigger_type", not "trigger" — the latter is a SQL keyword.
            conn.execute("""
                INSERT INTO control.task_history
                    (task_type, trigger_type, status, started_at, finished_at, detail)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task["task_type"], task["trigger"], status,
                  task["started_at"], time.time(), task["detail"]))
            conn.execute("""
                DELETE FROM control.task_history WHERE id NOT IN (
                    SELECT id FROM control.task_history
                    ORDER BY finished_at DESC LIMIT ?
                )
            """, (HISTORY_LIMIT,))
    except Exception:
        log.exception("Failed to persist task history for %s", task["task_type"])


def running() -> list[dict]:
    with _lock:
        return [dict(t) for t in _running.values()]


def recent(limit: int = 10) -> list[dict]:
    with db.db() as conn:
        rows = conn.execute("""
            SELECT task_type, trigger_type AS trigger, status, started_at, finished_at, detail
            FROM control.task_history ORDER BY finished_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]
