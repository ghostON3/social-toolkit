"""SocialPoster — Facade.

One class. Hides registry, factory, hooks, adapter lifecycle. The public API
you actually want to call from scripts:

    from social_poster import SocialPoster, CampaignBuilder

    poster = SocialPoster()
    poster.on("post_success", lambda evt, data: print(data["result"]))

    content = CampaignBuilder().from_directory("output/prague-carousel").build()
    results = poster.post(content, to=["ig", "bsky", "dc"])
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .content import CampaignBuilder, CampaignContent
from .factory import AdapterRegistry, PlatformInfo
from .hooks import HookSystem
from .result import PostResult


class SocialPoster:
    """Single entry point. Lazily creates + caches adapters as needed."""

    def __init__(self):
        self._adapters: dict[str, Any] = {}
        self._hooks = HookSystem()

    # ─── Introspection ───
    def available(self) -> list[PlatformInfo]:
        """Every registered platform with its constraints."""
        return AdapterRegistry.list_all()

    def is_logged_in(self, platform: str) -> bool:
        try:
            self._get_adapter(platform, load=True)
            return True
        except (FileNotFoundError, RuntimeError):
            return False

    # ─── Lifecycle ───
    def login(self, platform: str) -> None:
        """Interactive one-time login for a single platform."""
        adapter = self._get_adapter(platform, load=False)
        adapter.login()

    def whoami(self, platform: str) -> str:
        return self._get_adapter(platform).whoami()

    # ─── Core: post + delete ───
    def post(
        self,
        content: CampaignContent | str | Path,
        *,
        to: list[str],
        prefer_video: bool = False,
        gap_seconds: float = 0.0,
    ) -> dict[str, PostResult]:
        """Fan-out the same campaign to many platforms.

        `content` may be a CampaignContent, OR a path to a campaign directory
        (in which case CampaignBuilder.from_directory is used implicitly).

        If an adapter has no saved session, it's reported as a failure result
        rather than crashing the whole fan-out.
        """
        import os
        c = self._resolve(content)
        dry = os.environ.get("SOCIAL_POSTER_DRY_RUN") in ("1", "true", "yes")
        results: dict[str, PostResult] = {}
        for i, name in enumerate(to):
            if i > 0 and gap_seconds > 0:
                time.sleep(gap_seconds)
            try:
                adapter = self._get_adapter(name, load=not dry)
            except (FileNotFoundError, RuntimeError) as e:
                results[name] = PostResult.failure(name, f"not logged in (run sp-login {name})")
                self._hooks.emit("post_failure", platform=name, result=results[name])
                continue
            results[name] = adapter.post(c, prefer_video=prefer_video)
        return results

    def post_many(
        self,
        campaigns: list[CampaignContent | str | Path],
        *,
        to: list[str],
        prefer_video: bool = False,
        gap_seconds: float = 10.0,
    ) -> list[dict[str, PostResult]]:
        """Post multiple campaigns sequentially, sleeping `gap_seconds` between."""
        out: list[dict[str, PostResult]] = []
        for i, c in enumerate(campaigns):
            if i > 0 and gap_seconds > 0:
                time.sleep(gap_seconds)
            out.append(self.post(c, to=to, prefer_video=prefer_video))
        return out

    def delete(self, platform: str, media_id: str) -> bool:
        return self._get_adapter(platform).delete(media_id)

    # ─── Observer subscription ───
    def on(self, event: str, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Subscribe to a hook event. See hooks.py for the canonical event list."""
        self._hooks.on(event, callback)

    # ─── internals ───
    def _get_adapter(self, name: str, *, load: bool = True):
        if name in self._adapters:
            return self._adapters[name]
        adapter = AdapterRegistry.create(name)
        adapter.attach_hooks(self._hooks)
        if load:
            adapter.load()
        self._adapters[name] = adapter
        return adapter

    def _resolve(self, content: CampaignContent | str | Path) -> CampaignContent:
        if isinstance(content, CampaignContent):
            return content
        return CampaignBuilder().from_directory(content).build()
