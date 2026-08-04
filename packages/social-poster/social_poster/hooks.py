"""HookSystem — Observer pattern.

Subscribers register callables for named events. Producers emit events with
arbitrary kwargs. Callbacks that throw are swallowed (one bad listener can't
break a post).

Supported events (canonical):
  - "pre_post"        before any upload     payload: {platform, content}
  - "post_success"    after a successful post  payload: {platform, result}
  - "post_failure"    after a failed post      payload: {platform, result}
  - "pre_login"       before interactive login payload: {platform}
  - "login_success"   payload: {platform, identity}
  - "delete_success"  payload: {platform, media_id}
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


Event = str
Listener = Callable[[Event, dict[str, Any]], None]


class HookSystem:
    """One per Facade. Global helpers below for module-level subscribers."""

    def __init__(self):
        self._listeners: dict[Event, list[Listener]] = defaultdict(list)

    def on(self, event: Event, listener: Listener) -> None:
        self._listeners[event].append(listener)

    def off(self, event: Event, listener: Listener) -> None:
        if listener in self._listeners[event]:
            self._listeners[event].remove(listener)

    def emit(self, event: Event, **data: Any) -> None:
        for listener in self._listeners.get(event, []):
            try:
                listener(event, data)
            except Exception:
                # Swallow — one bad listener must not break a post.
                pass


# ─── Module-global hook system (handy when you don't want a Facade) ───
_global = HookSystem()


def on(event: Event, listener: Listener) -> None:
    """Subscribe globally — every Facade emits through this too."""
    _global.on(event, listener)


def emit(event: Event, **data: Any) -> None:
    _global.emit(event, **data)


def global_hooks() -> HookSystem:
    return _global
