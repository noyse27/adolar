"""Request- and thread-local snapshot of the active music library.

Gunicorn's gthread workers run several threads in each of several processes.
Mutable module globals therefore cannot safely represent the active library:
threads can race with a switch, and another worker will not see the mutation.

The registry remains the shared source of truth.  At the start of a request we
bind one immutable snapshot here; database access and filesystem path checks
then keep using that snapshot for the request's entire lifetime.  Background
threads explicitly inherit the snapshot that was current when they started.
"""

import contextlib
import contextvars
from collections.abc import Callable, Iterator
from typing import Any

_content_db_path: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adolar_content_db_path", default=None,
)
_music_root: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "adolar_music_root", default=None,
)


def content_db_path(default: str) -> str:
    return _content_db_path.get() or default


def music_root(default: str) -> str:
    return _music_root.get() or default


def snapshot(default_db_path: str, default_music_root: str) -> tuple[str, str]:
    return content_db_path(default_db_path), music_root(default_music_root)


@contextlib.contextmanager
def bind(db_path: str, root: str) -> Iterator[None]:
    db_token = _content_db_path.set(db_path)
    root_token = _music_root.set(root)
    try:
        yield
    finally:
        _music_root.reset(root_token)
        _content_db_path.reset(db_token)


def wrapped(
    target: Callable[..., Any],
    db_path: str,
    root: str,
) -> Callable[..., Any]:
    """Return a callable that runs ``target`` inside a captured snapshot."""

    def run(*args: Any, **kwargs: Any) -> Any:
        with bind(db_path, root):
            return target(*args, **kwargs)

    return run
