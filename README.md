# social-toolkit

**Read, understand and publish social content from Python.** Two independent
packages that share one idea: your social data and your sessions stay on your
machine.

| Package | What it does | Tests |
|---|---|---|
| [`instagram-dm-kit`](packages/instagram-dm-kit) | Read, send and **harvest** Instagram DMs — turn forwarded reels, posts and links into a structured corpus a RAG/LLM pipeline can actually use | 48 |
| [`social-poster`](packages/social-poster) | One facade, **12 platforms**, design-pattern bones — publish the same campaign everywhere with a dry-run-first API | 43 |

Each package installs and versions on its own. The monorepo exists because they
are two halves of one loop — **ingest ↔ publish** — and share conventions,
tooling and a session-safety model.

---

## Quickstart

```bash
git clone https://github.com/ghostON3/social-toolkit
cd social-toolkit

# harvest a DM thread into a knowledge corpus
pip install -e packages/instagram-dm-kit
idk login
idk threads
idk corpus --thread <id> --out corpus.jsonl

# publish one campaign directory (01.png … + caption.txt) to many platforms
pip install -e packages/social-poster
sp-post --to bsky,mast --dry-run ./my-campaign      # shorts: bsky dc fb ig mast pin rd tg th tt x yt
```

Reuse a browser login instead of typing a password (Firefox on macOS shown):

```bash
pip install -e 'packages/instagram-dm-kit[browser]'
IDK_SESSION=~/.config/social-poster/ig.json idk connect --browser firefox \
  --cookie-file "$HOME/Library/Application Support/Firefox/Profiles/<profile>/cookies.sqlite"
```

## Agents, schedules and CircleHash News

- `sp-mcp` (extra `mcp`) is a stdio MCP server over the facade: `platforms`, `sessions`,
  `whoami`, `post`, `schedule`, `list_schedule`, `set_status`, `publish`, `news_sync`.
  Everything is dry-run unless the call asks for live **and** the server runs with
  `SOCIAL_POSTER_MCP_ALLOW_LIVE=1`.
- `sp-publish --window 10` drains approved entries due in the window; run it from a
  launchd agent or cron. Entries start `pending`; approving is the human gate.
- `python -m connectors.circlehash_news_connector --client <id> --platforms ig`
  plans one post per unseen CircleHash news post (public `GET /api/public/news/v1`,
  or a saved JSON file) with the cover converted to JPEG.
- `sp-serve` needs the `server` extra: `uv run --all-extras sp-serve`.

## Design

**`instagram-dm-kit`** — a thin, lazily-imported core. The pure stages
(`normalize` / `harvest` / `corpus` / `view`) have **zero required
dependencies**; the network half is an optional extra. So you can parse and
reshape an export without installing an Instagram client at all.

**`social-poster`** — a registry of `PlatformAdapter` strategies behind a single
`SocialPoster` facade. Adapters are auto-discovered plugins; adding a platform
means dropping in one file. The patterns are deliberate and labelled in the
source: Factory Method, Builder, Singleton, Adapter, Facade, Decorator,
Strategy, Template Method, Observer.

```
social-toolkit/
├── packages/
│   ├── instagram-dm-kit/     # ingest  — read · understand · corpus
│   └── social-poster/        # publish — one facade, 12 adapters
└── pyproject.toml            # uv workspace
```

## Platform support in `social-poster`

Bluesky · Mastodon · Discord · Telegram · Reddit · YouTube · Pinterest ·
Facebook · Threads · TikTok · Twitter/X · Instagram

Each adapter declares its own capabilities (carousel limits, video support,
caption length), so the facade fans out only where a post actually makes sense.

## ⚠️ Read this before you use it

Some adapters — **Instagram**, **Twitter/X** — run on **unofficial,
reverse-engineered APIs** (`instagrapi`, `twikit`). Using them may violate the
platform's Terms of Service and **can get an account rate-limited, action-blocked
or permanently suspended.**

- Use them only on accounts you own.
- Prefer the official-API adapters (Bluesky, Mastodon, Discord, Telegram,
  Reddit, YouTube) where you can.
- `--dry-run` is the default on the posting path. Keep it that way until you are
  sure.

**On credentials:** `instagram-dm-kit` can reuse a browser session instead of
asking for your password. That `sessionid` is a **full-account bearer token**. It
is stored locally, is never transmitted anywhere except to Instagram by the
client library itself, and is git-ignored by default. Treat the file the way you
would treat your password.

This toolkit does nothing to hide automated activity from a platform, and it
should not be used for bulk unsolicited messaging.

## Development

```bash
uv sync --all-extras                    # per package
uv run pytest -q                        # 48 + 43 = 91 tests
```

Both packages test offline: every network call is mocked, and no test touches a
real account.

## License

MIT — see [LICENSE](LICENSE).
