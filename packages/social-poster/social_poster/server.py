"""FastAPI seam over the SocialPoster facade.

The HTTP surface the Social Injection Console FE calls. It is a thin transport
shell: every operation goes through the SocialPoster facade (and therefore
through the adapter Template Method, decorators, and hooks) — the server never
reaches past the facade into adapters or the registry directly for *actions*.

Endpoints:
  GET  /health             liveness
  GET  /platforms          registered adapters + capability metadata
  GET  /sessions           per-platform logged-in state
  POST /login {platform}   one-time interactive login (server-side stdin!)
  POST /post  {...}        fan-out a campaign; dry_run defaults TRUE

Run with:  sp-serve   (entry point) or  uvicorn social_poster.server:app
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import AdapterRegistry, CampaignBuilder, SocialPoster
from .config import DRY_RUN_DEFAULT, DRY_RUN_ENV, HOST, PORT
from .errors import NotSupported

# One process-wide facade — it lazily caches adapters, which is what we want
# (sessions stay warm between requests).
_poster = SocialPoster()

# The dry-run signal is an env var read inside the adapter template method.
# Toggling it per-request is global state, so guard it with a lock to keep
# concurrent /post calls from clobbering each other.
_dry_run_lock = Lock()


# ─────────────────────────── pydantic models ───────────────────────────

class PlatformOut(BaseModel):
    short: str
    display: str
    max_carousel: int
    supports_video: bool
    supports_comments: bool
    caption_max: int
    supports_post: bool = Field(description="False for non-feed platforms (e.g. Tinder)")


class SessionOut(BaseModel):
    platform: str
    logged_in: bool


class LoginIn(BaseModel):
    platform: str


class LoginOut(BaseModel):
    platform: str
    logged_in: bool
    whoami: str | None = None


class ContentIn(BaseModel):
    name: str = Field(default="api-campaign")
    slides: list[str] = Field(default_factory=list, description="image file paths")
    video: str | None = None
    thumbnail: str | None = None
    caption: str = ""
    first_comment: str = ""


class PostIn(BaseModel):
    platforms: list[str] = Field(min_length=1)
    content: ContentIn
    prefer_video: bool = False
    dry_run: bool | None = Field(
        default=None,
        description="When omitted, defaults to the server's safe default (TRUE). "
        "Set false to actually publish.",
    )


class PostResultOut(BaseModel):
    platform: str
    ok: bool
    media_id: str | None = None
    url: str | None = None
    error: str | None = None
    warning: str | None = None
    extras: dict = Field(default_factory=dict)


class PostOut(BaseModel):
    dry_run: bool
    results: list[PostResultOut]


# ─────────────────────────── helpers ───────────────────────────

@contextmanager
def _dry_run(enabled: bool) -> Iterator[None]:
    """Set/restore the dry-run env var the adapters honor, under a lock."""
    with _dry_run_lock:
        prev = os.environ.get(DRY_RUN_ENV)
        if enabled:
            os.environ[DRY_RUN_ENV] = "1"
        else:
            os.environ.pop(DRY_RUN_ENV, None)
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop(DRY_RUN_ENV, None)
            else:
                os.environ[DRY_RUN_ENV] = prev


def _supports_post(short: str) -> bool:
    klass = AdapterRegistry._classes.get(short)  # read-only introspection, not an action
    return bool(klass) and getattr(klass, "MAX_CAROUSEL", 0) >= 0


def _build_content(c: ContentIn):
    b = CampaignBuilder().named(c.name).with_caption(c.caption).with_first_comment(c.first_comment)
    if c.slides:
        b = b.with_slides(c.slides)
    if c.video:
        b = b.with_video(c.video)
    if c.thumbnail:
        b = b.with_thumbnail(c.thumbnail)
    return b.build()


# ─────────────────────────── app ───────────────────────────

app = FastAPI(
    title="social-poster",
    version="0.2.0",
    description="HTTP seam over the SocialPoster facade. dry_run defaults TRUE.",
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "dry_run_default": DRY_RUN_DEFAULT}


@app.get("/platforms", response_model=list[PlatformOut])
def platforms() -> list[PlatformOut]:
    out: list[PlatformOut] = []
    for info in _poster.available():
        out.append(
            PlatformOut(
                short=info.short,
                display=info.display,
                max_carousel=info.max_carousel,
                supports_video=info.supports_video,
                supports_comments=info.supports_comments,
                caption_max=info.caption_max,
                supports_post=info.max_carousel >= 0,
            )
        )
    return out


@app.get("/sessions", response_model=list[SessionOut])
def sessions() -> list[SessionOut]:
    return [
        SessionOut(platform=info.short, logged_in=_poster.is_logged_in(info.short))
        for info in _poster.available()
    ]


@app.post("/login", response_model=LoginOut)
def login(body: LoginIn) -> LoginOut:
    if body.platform not in AdapterRegistry.names():
        raise HTTPException(status_code=404, detail=f"unknown platform '{body.platform}'")
    try:
        _poster.login(body.platform)
    except Exception as e:  # interactive login can fail many ways; surface a clean message
        raise HTTPException(status_code=400, detail=f"login failed: {type(e).__name__}: {e}")
    who: str | None = None
    try:
        who = _poster.whoami(body.platform)
    except Exception:
        who = None
    return LoginOut(platform=body.platform, logged_in=_poster.is_logged_in(body.platform), whoami=who)


@app.post("/post", response_model=PostOut)
def post(body: PostIn) -> PostOut:
    unknown = [p for p in body.platforms if p not in AdapterRegistry.names()]
    if unknown:
        raise HTTPException(status_code=404, detail=f"unknown platforms: {unknown}")

    dry = DRY_RUN_DEFAULT if body.dry_run is None else body.dry_run
    content = _build_content(body.content)

    try:
        with _dry_run(dry):
            results = _poster.post(content, to=body.platforms, prefer_video=body.prefer_video)
    except NotSupported as e:
        raise HTTPException(status_code=422, detail=str(e))

    return PostOut(
        dry_run=dry,
        results=[
            PostResultOut(
                platform=r.platform,
                ok=r.ok,
                media_id=r.media_id,
                url=r.url,
                error=r.error,
                warning=r.warning,
                extras=r.extras,
            )
            for r in results.values()
        ],
    )


def serve() -> None:
    """Entry point for `sp-serve`."""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # server deps are an optional extra
        raise SystemExit(
            "sp-serve needs the HTTP server extra. Install it with:\n"
            "  pip install 'social-poster[server]'\n"
            "  (or: uv pip install 'social-poster[server]')"
        ) from exc

    uvicorn.run("social_poster.server:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    serve()
