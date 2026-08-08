#!/usr/bin/env python3
"""Append the managed AGENTS.md snippet once without replacing user content."""

from __future__ import annotations

import argparse
import os
import stat
import tempfile
from pathlib import Path


MARKER = "## Versatile development workflow"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("snippet", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = args.target.read_text(encoding="utf-8") if args.target.exists() else ""
    if MARKER in current:
        return 0
    if args.check:
        return 1

    addition = args.snippet.read_text(encoding="utf-8").strip() + "\n"
    separator = "\n\n" if current.strip() else ""
    atomic_write(args.target, current.rstrip() + separator + addition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
