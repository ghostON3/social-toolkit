"""Decorator pattern — cross-cutting concerns for adapter methods.

These wrap `_do_post` / `_do_login` / `_do_*` so each adapter doesn't have to
hand-roll retry/auth/dry-run logic.

Usage in an adapter:

    @retry(times=2, on=(PleaseWaitFewMinutes, RateLimitError), backoff=4)
    def _do_post(self, content, prefer_video):
        ...
"""
from __future__ import annotations

import functools
import os
import time
from typing import Callable, Type, TypeVar


F = TypeVar("F", bound=Callable)


def retry(*, times: int = 2, on: tuple[Type[BaseException], ...] = (Exception,), backoff: float = 2.0) -> Callable[[F], F]:
    """Re-run on listed exceptions with exponential backoff."""
    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            last: BaseException | None = None
            for attempt in range(times + 1):
                try:
                    return fn(*args, **kwargs)
                except on as e:
                    last = e
                    if attempt == times:
                        raise
                    delay = backoff ** attempt
                    time.sleep(delay)
            assert last is not None
            raise last
        return wrapped  # type: ignore[return-value]
    return deco


def require_session(fn: F) -> F:
    """Refuse to run if the adapter hasn't loaded a session yet."""
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        if not getattr(self, "_session_loaded", False):
            raise RuntimeError(
                f"{type(self).__name__} session not loaded — call .load() or .login() first"
            )
        return fn(self, *args, **kwargs)
    return wrapped  # type: ignore[return-value]


def dry_run_safe(fn: F) -> F:
    """Skip the wrapped call when SOCIAL_POSTER_DRY_RUN=1 in the env.

    For methods that return PostResult, returns a synthetic success result.
    """
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        if os.environ.get("SOCIAL_POSTER_DRY_RUN") in ("1", "true", "yes"):
            from .result import PostResult
            short = getattr(self, "SHORT_NAME", "?")
            return PostResult(platform=short, ok=True, media_id="DRY-RUN",
                              url=None, extras={"dry_run": True})
        return fn(self, *args, **kwargs)
    return wrapped  # type: ignore[return-value]


def log_step(name: str | None = None) -> Callable[[F], F]:
    """Emit a 'step_<name>' event before + after the wrapped call (Observer hook).

    Cheap profiling / breadcrumb without coupling to a logger.
    """
    from .hooks import emit

    def deco(fn: F) -> F:
        step = name or fn.__name__

        @functools.wraps(fn)
        def wrapped(self, *args, **kwargs):
            short = getattr(self, "SHORT_NAME", "?")
            emit(f"step_{step}_started", platform=short)
            try:
                out = fn(self, *args, **kwargs)
                emit(f"step_{step}_finished", platform=short)
                return out
            except Exception as e:
                emit(f"step_{step}_failed", platform=short, error=str(e))
                raise

        return wrapped  # type: ignore[return-value]

    return deco
