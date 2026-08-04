"""Console-script launcher for `sp-serve`.

Kept separate from `server.py` so the entry point can produce a clean,
actionable message when the optional HTTP server extra is not installed.
`server.py` imports FastAPI at module top level; importing it directly from
the entry point would raise a bare ModuleNotFoundError before any of our code
runs. This shim checks for the extra first.
"""
from __future__ import annotations


def main() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "sp-serve needs the HTTP server extra. Install it with:\n"
            "  pip install 'social-poster[server]'\n"
            "  (or: uv pip install 'social-poster[server]')"
        ) from exc

    from .server import serve

    serve()


if __name__ == "__main__":
    main()
