# social-poster

Multi-platform social media poster. One facade, twelve platforms, design-pattern bones.

```
social-poster/
├── pyproject.toml             # installable; CLI entry points: sp-login / sp-post / sp-delete
├── social_poster/             # the library
│   ├── __init__.py            # public API exports
│   ├── base.py                # PlatformAdapter ABC          ← Template Method + Strategy + Adapter
│   ├── content.py             # CampaignContent + Builder    ← Builder
│   ├── result.py              # PostResult                   ← Value Object
│   ├── factory.py             # AdapterRegistry              ← Factory Method + Singleton + plugin discovery
│   ├── facade.py              # SocialPoster                 ← Facade
│   ├── hooks.py               # HookSystem                   ← Observer
│   ├── decorators.py          # @retry, @require_session, …  ← Decorator
│   ├── cli.py                 # CLI entry points
│   └── adapters/              # plug-ins, auto-discovered    ← Strategy / Adapter
│       ├── instagram.py · bluesky.py · mastodon.py · discord.py
│       ├── reddit.py · telegram.py · youtube.py · twitter.py
│       └── threads.py · tiktok.py · pinterest.py · facebook.py
├── bin/                       # dev wrappers (same as sp-* CLIs)
└── tests/                     # 22 smoke tests
```

## Design patterns (refactoring.guru taxonomy)

| Category | Pattern | Where |
|---|---|---|
| **Creational** | Factory Method | `AdapterRegistry.create("ig")` returns the right subclass |
|  | Builder | `CampaignBuilder().from_directory(...).with_caption(...).build()` |
|  | Singleton | `AdapterRegistry` (process-global state + cache) |
| **Structural** | Adapter | each `*.py` in `adapters/` wraps a different SDK behind one interface |
|  | Facade | `SocialPoster` — one class, all 12 platforms |
|  | Decorator | `@retry`, `@require_session`, `@dry_run_safe`, `@log_step` |
| **Behavioral** | Strategy | each adapter = interchangeable algorithm for "post to social" |
|  | Template Method | `PlatformAdapter.post()` skeleton; subclasses fill in `_do_post`, `_do_first_comment`, `_do_login`, `_do_load_session`, `_do_delete` |
|  | Observer | `poster.on("post_success", cb)`; emitted events: `pre_post`, `post_success`, `post_failure`, `pre_login`, `login_success`, `delete_success` |

## Install (one-time)

```bash
cd packages/social-poster
./.venv/bin/pip install -e .
```

CLI scripts `sp-login` / `sp-post` / `sp-delete` land in `.venv/bin/`.

## Use it from code (the Facade)

```python
from social_poster import SocialPoster, CampaignBuilder

poster = SocialPoster()

# Subscribe to events (Observer)
poster.on("post_success", lambda evt, data: print(f"✓ {data['platform']}: {data['result'].url}"))
poster.on("post_failure", lambda evt, data: print(f"✗ {data['platform']}: {data['result'].error}"))

# Build a campaign (Builder) — or use from_directory shortcut
content = (CampaignBuilder()
    .named("prague-launch")
    .from_directory("output/prague-carousel")
    .build())

# Fan out (Facade hides factory + load + posting + comment)
results = poster.post(content, to=["ig", "bsky", "mast", "dc"], gap_seconds=5)

for platform, result in results.items():
    print(result)
```

## Use it from the CLI

```bash
# One-time login per platform
sp-login ig
sp-login bsky
sp-login mast
sp-login dc          # easiest — just a webhook URL

# Fan out to many platforms at once
sp-post --to=ig,bsky,mast,dc ./examples/output/prague-carousel

# Multiple campaigns with a 10s gap between each (and between platforms inside each)
sp-post --to=ig,bsky --gap=10 \
    ./examples/output/prague-carousel \
    ./examples/output/barcelona-carousel

# Reel mode (uses *.mp4 instead of carousel PNGs where possible)
sp-post --to=ig --video ./examples/output/prague-anim-proto

# Dry-run — no platform touched, just walks the plan
sp-post --to=ig,bsky,mast,dc,rd,tg,yt,x,th,tt,pin --dry-run \
    ./examples/output/prague-carousel

# Delete a post
sp-delete ig <media_id>
```

## Adding a new platform (5 minutes)

1. Create `social_poster/adapters/<name>.py`
2. Subclass `PlatformAdapter`, decorate with `@register("<short>", display="<Pretty>")`
3. Implement four hooks: `_do_login`, `_do_load_session`, `_do_post`, `whoami` (+ optional `_do_first_comment`, `_do_delete`)
4. Set class-level constants (`MAX_CAROUSEL`, `CAPTION_MAX`, `SUPPORTS_VIDEO`, `SUPPORTS_COMMENTS`)
5. Done — auto-discovered on next import, CLI knows the short name

Example minimal skeleton:

```python
from ..base import PlatformAdapter
from ..content import CampaignContent
from ..factory import register
from ..result import PostResult

@register("xyz", display="XYZ Network")
class XYZ(PlatformAdapter):
    MAX_CAROUSEL = 5
    CAPTION_MAX = 1000

    def _do_login(self):
        # prompt user, save session to self.session_path
        ...

    def _do_load_session(self):
        if not self.session_path.exists():
            raise FileNotFoundError(self.session_path)
        # load saved creds

    def _do_post(self, content: CampaignContent, *, prefer_video: bool) -> PostResult:
        # upload + publish; return PostResult.success(...) or .failure(...)
        ...

    def _do_first_comment(self, media_id: str, text: str) -> None:
        # optional; default = no-op
        ...

    def whoami(self) -> str:
        return "..."
```

The template method in `PlatformAdapter.post()` handles:
- Caption + first-comment truncation
- `pre_post` / `post_success` / `post_failure` event emission
- Dry-run interception (`SOCIAL_POSTER_DRY_RUN=1`)
- First-comment dispatch (only if `SUPPORTS_COMMENTS` and content provides one)
- Exception trapping → `PostResult.failure`

You write only the platform-specific bits.

## Platform catalog

| Short | Platform | Carousel | Video | Comments | Caption | Setup cost |
|---|---|---|---|---|---|---|
| `ig` | Instagram | 10 | reels | yes | 2200 | username + password (+ 2FA) |
| `bsky` | Bluesky | 4 | yes | reply | 300 | handle + **app password** |
| `mast` | Mastodon | 4 | yes | reply | 500 | instance + creds |
| `dc` | Discord | 10 | yes | follow-up msg | 2000 | **just a webhook URL** |
| `rd` | Reddit | 20 | yes | yes | 40000 | client_id/secret + creds |
| `tg` | Telegram | 10 | yes | reply | 1024 | api_id + api_hash + phone |
| `yt` | YouTube | 1 video | yes | comment thread | 5000 | OAuth client.json + browser consent |
| `x` | Twitter / X | 4 | yes | reply | 280 | username + email + password (fragile) |
| `th` | Threads | 10 | yes | reply | 500 | Meta dev app + token + **public media URLs** |
| `tt` | TikTok | 1 video | yes | n/a | 2200 | TikTok dev app + token + **public video URL** |
| `pin` | Pinterest | 1 pin | yes | n/a | 800 | Pinterest dev app + token + board_id |
| `fb` | Facebook | 10 | yes | n/a | 5000 | Meta dev app + page token |

## Tests

```bash
uv sync --all-extras
uv run pytest -q
```

43 tests cover: registry discovery, registry metadata, builder fluent API, content immutability, result factories, observer wiring, template method calling first-comment, template method truncating long captions.

## What changed from v0.1

- Flat `adapters/` dir → proper `social_poster/` Python package (`pip install -e .`)
- Manual `REGISTRY` dict + `register()` function → `AdapterRegistry` singleton with plugin auto-discovery
- Each adapter's `post()` method (40-90 LOC of similar boilerplate per platform) → 1 `_do_post()` of pure platform-specific upload code
- CLI scripts shelling out to `python -m` → installed entry points (`sp-login`, `sp-post`, `sp-delete`)
- Mutable `CampaignContent` dataclass → frozen value object with fluent `Builder`
- Ad-hoc `print()` logging → pluggable `Observer` events (`pre_post`, `post_success`, `post_failure`, …)
- Dry-run logic scattered → single env-var check in the template method (uniform across adapters)
- No tests → 8 smoke tests covering the design patterns

If you previously called `from adapters import REGISTRY`, switch to `from social_poster import AdapterRegistry; AdapterRegistry.names()`.

## Legal & platform terms (read before use)

This library automates posting to third-party platforms. Several adapters use
**unofficial / reverse-engineered APIs**, which may violate the platform's Terms
of Service and can result in rate-limiting, content removal, or account
suspension. Use them at your own risk and only on accounts you own.

| Adapter | Transport | Status |
|---|---|---|
| Instagram | `instagrapi` (unofficial) | ⚠ ToS-gray |
| Twitter/X | `twikit` (unofficial) | ⚠ ToS-gray |
| Bluesky, Mastodon, Discord, Reddit, Telegram, YouTube, Pinterest | official SDK/API | ✓ supported |
| Threads, TikTok, Facebook | official API (scoped) | ✓ supported |

No warranty is provided (MIT). You are responsible for compliance with each
platform's developer agreement and applicable law in your jurisdiction.
`dry_run` defaults to **true** on the server surface — nothing is published until
you explicitly opt in.
