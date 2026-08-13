"""Convenient source-checkout launcher for Entity Map."""

from __future__ import annotations

import sys

from entity_map.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["serve", *sys.argv[1:]]))
