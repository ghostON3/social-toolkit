# social-toolkit
<!-- CLAUDE.md is a symlink to this file; edit only AGENTS.md. -->

This dormant Python workspace contains independently installable packages for social content ingestion and publishing. The default branch is `main`.

## Layout

`packages/instagram-dm-kit/` handles ingestion. `packages/social-poster/` handles publishing. Each package has its own `pyproject.toml`, README and tests. `connectors/` contains a standalone integration. `.venv/`, `dist/` and `build/` are generated, do not edit.

## Commands

Use Python 3.10+ and uv. From each package directory run `uv sync --all-extras`, then `uv run pytest -q`. Both runs are the proof for a change. The package CLIs include `idk` and `sp-post`. For a non-posting CLI smoke check, pass `sp-post --to <platforms> --dry-run <campaign-dir>` explicitly.

## How a change lands

Open a PR targeting `main`. The CI workflow runs both package test suites on pull requests and pushes to `main`. The checkout defines no auto-merge or Git hooks.

## Rules

Keep account sessions, environment files, harvested data and downloaded media out of Git. Keep the test suites offline with mocked platform access. Follow the [MIT license](LICENSE).

## More

- [Workspace README](README.md)
- [Ingestion package](packages/instagram-dm-kit/README.md)
- [Publishing package](packages/social-poster/README.md)
