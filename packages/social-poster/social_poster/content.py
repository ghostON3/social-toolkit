"""CampaignContent (value object) + CampaignBuilder (Builder pattern).

A campaign = "the stuff you want to post in one drop": slides, optional video,
caption, optional first comment. Built once, fanned out to N platforms.

Two construction paths:
  - Builder fluent API for code (`CampaignBuilder().with_caption("...").build()`)
  - `from_directory()` shortcut that reads a `social-post-maker`-shaped dir
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class CampaignContent:
    """Immutable value object. Use `replace()` (built-in dataclass) to derive variants."""
    name: str
    slides: tuple[Path, ...]
    video: Path | None
    thumbnail: Path | None
    caption: str
    first_comment: str

    def with_caption(self, caption: str) -> "CampaignContent":
        return replace(self, caption=caption)

    def with_first_comment(self, comment: str) -> "CampaignContent":
        return replace(self, first_comment=comment)

    def __str__(self) -> str:
        return (
            f"<CampaignContent {self.name!r} "
            f"slides={len(self.slides)} "
            f"video={'yes' if self.video else 'no'} "
            f"caption={len(self.caption)}c "
            f"first_comment={len(self.first_comment)}c>"
        )


class CampaignBuilder:
    """Fluent builder. Final `.build()` returns an immutable CampaignContent.

    Example:
        content = (CampaignBuilder()
            .named("prague-launch")
            .add_slide("01.png")
            .add_slide("02.png")
            .with_video("anim.mp4")
            .with_caption("🚀 New deal")
            .with_first_comment("#travel #europe")
            .build())
    """

    def __init__(self):
        self._name: str = ""
        self._slides: list[Path] = []
        self._video: Path | None = None
        self._thumbnail: Path | None = None
        self._caption: str = ""
        self._first_comment: str = ""

    # ─── Chainable setters ───
    def named(self, name: str) -> "CampaignBuilder":
        self._name = name
        return self

    def add_slide(self, path: str | Path) -> "CampaignBuilder":
        self._slides.append(Path(path))
        return self

    def with_slides(self, paths: list[str | Path]) -> "CampaignBuilder":
        self._slides = [Path(p) for p in paths]
        return self

    def with_video(self, path: str | Path) -> "CampaignBuilder":
        self._video = Path(path)
        return self

    def with_thumbnail(self, path: str | Path) -> "CampaignBuilder":
        self._thumbnail = Path(path)
        return self

    def with_caption(self, caption: str) -> "CampaignBuilder":
        self._caption = caption
        return self

    def with_first_comment(self, comment: str) -> "CampaignBuilder":
        self._first_comment = comment
        return self

    # ─── Convenience loader from a social-post-maker-shaped directory ───
    def from_directory(self, directory: str | Path) -> "CampaignBuilder":
        d = Path(directory)
        if not d.is_dir():
            raise FileNotFoundError(f"not a directory: {d}")

        self._name = self._name or d.name

        slides = sorted(
            p for p in d.iterdir()
            if p.suffix.lower() == ".png" and p.stem[:2].isdigit() and "-" not in p.stem
        )
        if not slides:
            any_pngs = sorted(p for p in d.iterdir() if p.suffix.lower() == ".png")
            if any_pngs:
                slides = [any_pngs[0]]
        self._slides = slides

        videos = sorted(p for p in d.iterdir() if p.suffix.lower() == ".mp4")
        if videos:
            self._video = videos[0]

        if slides:
            self._thumbnail = slides[0]

        cap_path = d / "caption.txt"
        if cap_path.exists():
            self._caption = cap_path.read_text("utf-8").strip()

        fc_path = d / "first-comment.txt"
        if fc_path.exists():
            self._first_comment = fc_path.read_text("utf-8").strip()

        return self

    # ─── Terminal ───
    def build(self) -> CampaignContent:
        if not self._name:
            raise ValueError("CampaignBuilder: name is required")
        return CampaignContent(
            name=self._name,
            slides=tuple(self._slides),
            video=self._video,
            thumbnail=self._thumbnail,
            caption=self._caption,
            first_comment=self._first_comment,
        )
