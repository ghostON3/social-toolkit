"""social_poster — multi-platform poster with proper design-pattern bones.

Public API (everything you should need is reachable from here):

    SocialPoster              Facade — one class, all platforms
    CampaignContent           Value object describing what to post
    CampaignBuilder           Fluent Builder for CampaignContent
    PostResult                Value object every adapter returns
    PlatformInfo              Metadata about a registered platform
    register                  Decorator to register your own adapter
    PlatformAdapter           Base class if you extend with a new platform
    hooks                     Module — `from social_poster import hooks`

Design patterns in use (refactoring.guru taxonomy):
    Creational : Factory Method (AdapterRegistry), Builder (CampaignBuilder), Singleton (registry)
    Structural : Adapter (each PlatformAdapter), Facade (SocialPoster), Decorator (retry/require_session/dry_run_safe/log_step)
    Behavioral : Strategy (each adapter), Template Method (PlatformAdapter.post), Observer (HookSystem)
"""
from __future__ import annotations

from .base import PlatformAdapter
from .content import CampaignBuilder, CampaignContent
from .decorators import dry_run_safe, log_step, require_session, retry
from .facade import SocialPoster
from .factory import AdapterRegistry, PlatformInfo, register
from .result import PostResult
from . import hooks

__all__ = [
    "SocialPoster",
    "CampaignContent",
    "CampaignBuilder",
    "PostResult",
    "PlatformInfo",
    "PlatformAdapter",
    "AdapterRegistry",
    "register",
    "retry",
    "require_session",
    "dry_run_safe",
    "log_step",
    "hooks",
]
