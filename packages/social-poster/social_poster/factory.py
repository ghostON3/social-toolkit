"""AdapterRegistry — Singleton + Factory Method.

Adapters register themselves via the `@register("short_name", display="Pretty")`
decorator at import time. The registry is process-global (Singleton). Use it
through the class methods; don't reach into the internal dict.

Adapters under `social_poster.adapters.*` auto-discover on first import of
`social_poster.adapters` — drop a new module in there and it just works.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from .base import PlatformAdapter


@dataclass(frozen=True)
class PlatformInfo:
    short: str
    display: str
    max_carousel: int
    supports_video: bool
    supports_comments: bool
    caption_max: int


class AdapterRegistry:
    """Singleton (module-level state). Public access via classmethods."""

    _classes: dict[str, Type["PlatformAdapter"]] = {}
    _discovered: bool = False

    # ─── Registration (called by the @register decorator) ───
    @classmethod
    def _register(cls, name: str, klass: Type["PlatformAdapter"]) -> None:
        if name in cls._classes and cls._classes[name] is not klass:
            raise ValueError(f"adapter '{name}' already registered to {cls._classes[name]!r}")
        cls._classes[name] = klass

    # ─── Discovery ───
    @classmethod
    def discover(cls) -> None:
        if cls._discovered:
            return
        cls._discovered = True
        from . import adapters as adapters_pkg
        for mod_info in pkgutil.iter_modules(adapters_pkg.__path__):
            if mod_info.name.startswith("_"):
                continue
            importlib.import_module(f"{adapters_pkg.__name__}.{mod_info.name}")

    # ─── Factory Method ───
    @classmethod
    def create(cls, name: str) -> "PlatformAdapter":
        cls.discover()
        if name not in cls._classes:
            raise KeyError(
                f"unknown platform '{name}'. Available: {sorted(cls._classes)}"
            )
        return cls._classes[name]()

    # ─── Introspection ───
    @classmethod
    def list_all(cls) -> list[PlatformInfo]:
        cls.discover()
        out = []
        for short, k in sorted(cls._classes.items()):
            out.append(PlatformInfo(
                short=short,
                display=getattr(k, "DISPLAY_NAME", short.upper()),
                max_carousel=k.MAX_CAROUSEL,
                supports_video=k.SUPPORTS_VIDEO,
                supports_comments=k.SUPPORTS_COMMENTS,
                caption_max=k.CAPTION_MAX,
            ))
        return out

    @classmethod
    def names(cls) -> list[str]:
        cls.discover()
        return sorted(cls._classes)


def register(short: str, *, display: str | None = None):
    """Decorator: bind a PlatformAdapter subclass to a short name in the registry.

    Required by EVERY adapter:

        @register("ig", display="Instagram")
        class Instagram(PlatformAdapter):
            ...
    """
    def deco(cls):
        cls.SHORT_NAME = short
        cls.DISPLAY_NAME = display or short.upper()
        AdapterRegistry._register(short, cls)
        return cls
    return deco
