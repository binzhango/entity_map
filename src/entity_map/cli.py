"""Command-line entry point for Entity Map."""

from __future__ import annotations

import argparse
import threading
from typing import Sequence
import webbrowser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entity-map",
        description="Explore legacy-to-current database field mappings locally.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the local Entity Map server")
    serve.add_argument("--port", type=int, default=8501, help="Local TCP port (default: 8501)")
    serve.add_argument(
        "--no-browser", action="store_true", help="Do not open the application in a browser"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "serve":
        return 2
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")

    import uvicorn

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        opener = threading.Timer(0.8, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    uvicorn.run(
        "entity_map.app:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
