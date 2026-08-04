"""Named exceptions for social_poster.

Kept tiny on purpose — the library leans on PostResult.failure for *expected*
per-platform failures (rate limits, not-logged-in). These exceptions are for
*structural* mismatches: an operation a platform simply does not have.
"""
from __future__ import annotations


class SocialPosterError(Exception):
    """Base for all library-raised errors."""


class NotSupported(SocialPosterError):
    """A platform adapter was asked to perform an operation it does not have.

    Example: calling `post()` on a DM-only platform like Tinder. This is not a
    transient failure to be retried — it is a category error, so it raises
    rather than returning a PostResult.failure.
    """

    def __init__(self, platform: str, operation: str, *, hint: str | None = None):
        self.platform = platform
        self.operation = operation
        msg = f"{platform!r} does not support operation {operation!r}"
        if hint:
            msg += f" — {hint}"
        super().__init__(msg)
