"""PlatformAdapter — Template Method + Strategy + Adapter (the wrap-an-SDK kind).

Defines the algorithm skeleton for posting to any platform. Subclasses fill in
the platform-specific atomic operations (`_do_post`, `_do_login`, etc.) and the
class-level metadata (`MAX_CAROUSEL`, `CAPTION_MAX`, …).

You almost never need to override `post()`, `login()`, or `delete()` themselves —
they're the template; override the `_do_*` hooks instead.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from .content import CampaignContent
from .hooks import HookSystem, global_hooks
from .result import PostResult

SESSIONS_DIR = Path.home() / ".config" / "social-poster"


class PlatformAdapter(ABC):
    """Base class for every platform integration.

    Class-level metadata (override in each subclass via the @register decorator
    or as class attributes):
      SHORT_NAME       short id used on CLI / facade.post(to=[...])  (set by @register)
      DISPLAY_NAME     human-readable                                 (set by @register)
      MAX_CAROUSEL     -1 = unsupported, otherwise max image count
      SUPPORTS_VIDEO   bool
      SUPPORTS_COMMENTS bool — first-comment after post
      CAPTION_MAX      character cap for the main caption
      COMMENT_MAX      character cap for first-comment (defaults to CAPTION_MAX)
    """

    SHORT_NAME: ClassVar[str] = "abstract"
    DISPLAY_NAME: ClassVar[str] = "Abstract"
    MAX_CAROUSEL: ClassVar[int] = 10
    SUPPORTS_VIDEO: ClassVar[bool] = True
    SUPPORTS_COMMENTS: ClassVar[bool] = True
    CAPTION_MAX: ClassVar[int] = 2200
    COMMENT_MAX: ClassVar[int | None] = None  # falls back to CAPTION_MAX when None

    def __init__(self):
        self._session_loaded = False
        self._hooks: HookSystem | None = None
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(SESSIONS_DIR, 0o700)
        except OSError:
            pass

    # ────────────────────────────────────────────────────────────
    # Public template methods — DO NOT override in subclasses
    # ────────────────────────────────────────────────────────────

    def post(self, content: CampaignContent, *, prefer_video: bool = False) -> PostResult:
        """Template method. Normalize → emit pre → delegate → maybe-comment → emit post.

        Honors `SOCIAL_POSTER_DRY_RUN=1` env var: returns a synthetic success
        without touching the platform. Set at the template-method level so it
        applies uniformly to all adapters.
        """
        normalized = self._normalize(content)
        self._emit("pre_post", platform=self.SHORT_NAME, content=normalized)

        if os.environ.get("SOCIAL_POSTER_DRY_RUN") in ("1", "true", "yes"):
            result = PostResult(
                platform=self.SHORT_NAME, ok=True,
                media_id="DRY-RUN", url=None, extras={"dry_run": True},
            )
            self._emit("post_success", platform=self.SHORT_NAME, result=result)
            return result

        try:
            result = self._do_post(normalized, prefer_video=prefer_video)
        except Exception as e:
            result = PostResult.failure(self.SHORT_NAME, f"{type(e).__name__}: {e}")

        if (
            result.ok
            and self.SUPPORTS_COMMENTS
            and normalized.first_comment
            and result.media_id
        ):
            try:
                self._do_first_comment(result.media_id, normalized.first_comment)
            except Exception as e:
                result.warning = f"first_comment_failed: {e}"

        self._emit(
            "post_success" if result.ok else "post_failure",
            platform=self.SHORT_NAME,
            result=result,
        )
        return result

    def login(self) -> None:
        """Template method for one-time interactive login."""
        self._emit("pre_login", platform=self.SHORT_NAME)
        self._do_login()
        self._session_loaded = True
        try:
            identity = self.whoami()
        except Exception:
            identity = ""
        self._emit("login_success", platform=self.SHORT_NAME, identity=identity)

    def load(self) -> None:
        """Load previously-saved session (no UI)."""
        self._do_load_session()
        self._session_loaded = True

    def delete(self, media_id: str) -> bool:
        ok = self._do_delete(media_id)
        if ok:
            self._emit("delete_success", platform=self.SHORT_NAME, media_id=media_id)
        return ok

    # ────────────────────────────────────────────────────────────
    # Abstract hooks — subclasses MUST implement
    # ────────────────────────────────────────────────────────────

    @abstractmethod
    def _do_login(self) -> None:
        """Prompt user and save the session/credentials to `session_path`."""

    @abstractmethod
    def _do_load_session(self) -> None:
        """Restore session from `session_path`. Raise FileNotFoundError if missing."""

    @abstractmethod
    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        """Platform-specific upload + publish. Return PostResult."""

    @abstractmethod
    def whoami(self) -> str:
        """Human-readable identity (e.g. '@yourhandle · 2 followers')."""

    # ────────────────────────────────────────────────────────────
    # Optional overrides — sane defaults provided
    # ────────────────────────────────────────────────────────────

    def _do_first_comment(self, media_id: str, text: str) -> None:
        """Override if the platform has a real comments API. Default = no-op."""
        return

    def _do_delete(self, media_id: str) -> bool:
        raise NotImplementedError(f"{self.SHORT_NAME} adapter does not support delete()")

    # ────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────

    @property
    def session_path(self) -> Path:
        # Read at call time so per-client credential dirs work (set via
        # ClientRecord.set_env_for_platform before each post call).
        base = Path(os.environ.get("SOCIAL_POSTER_SESSION_DIR", str(SESSIONS_DIR)))
        return base / f"{self.SHORT_NAME}.json"

    def attach_hooks(self, hooks: HookSystem) -> None:
        self._hooks = hooks

    def truncate(self, text: str, *, max_len: int | None = None) -> str:
        n = max_len if max_len is not None else self.CAPTION_MAX
        if len(text) <= n:
            return text
        return text[: n - 1].rstrip() + "…"

    # ─── internal ───
    def _emit(self, event: str, **data) -> None:
        global_hooks().emit(event, **data)
        if self._hooks is not None:
            self._hooks.emit(event, **data)

    def _normalize(self, content: CampaignContent) -> CampaignContent:
        caption = self.truncate(content.caption, max_len=self.CAPTION_MAX)
        cmax = self.COMMENT_MAX if self.COMMENT_MAX is not None else self.CAPTION_MAX
        comment = self.truncate(content.first_comment, max_len=cmax) if self.SUPPORTS_COMMENTS else ""
        return content.with_caption(caption).with_first_comment(comment)
