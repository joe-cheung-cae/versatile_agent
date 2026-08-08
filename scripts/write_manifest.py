#!/usr/bin/env python3
"""Write an atomic, machine-readable routing and installation manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--probe", type=Path)
    args = parser.parse_args()

    probe = {}
    if args.probe and args.probe.exists():
        probe = json.loads(args.probe.read_text(encoding="utf-8"))

    document = {
        "schema_version": 1,
        "bundle_version": args.source_version,
        "installed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": args.scope,
        "selected_profile": args.profile,
        "luna_requested": args.profile.startswith("luna-"),
        "fallback_model": "gpt-5.6-terra",
        "fallback_strategy": "selected Terra profile, then explicit Terra spawn, then code_mapper",
        "runtime_probe": probe,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{args.output.name}.", dir=args.output.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, args.output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
