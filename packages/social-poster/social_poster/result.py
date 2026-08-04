"""PostResult — value object returned by every adapter.

Refactoring.guru calls this kind of thing a "Special Case" pattern (Fowler);
we use it as a tagged-union-lite. Construct via the factories `success()` /
`failure()` so the call site reads naturally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PostResult:
    platform: str
    ok: bool
    media_id: str | None = None
    url: str | None = None
    error: str | None = None
    warning: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    # ─── Factories ───
    @classmethod
    def success(cls, platform: str, media_id: str, url: str | None = None, **extras) -> "PostResult":
        return cls(platform=platform, ok=True, media_id=media_id, url=url, extras=extras)

    @classmethod
    def failure(cls, platform: str, error: str, **extras) -> "PostResult":
        return cls(platform=platform, ok=False, error=error, extras=extras)

    # ─── Display ───
    def __str__(self) -> str:
        if self.ok:
            base = f"✓ {self.platform}"
            if self.url:
                base += f" → {self.url}"
            if self.warning:
                base += f" (⚠ {self.warning})"
            return base
        return f"✗ {self.platform}: {self.error}"
