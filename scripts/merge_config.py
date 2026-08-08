#!/usr/bin/env python3
"""Safely merge the managed [agents] keys while preserving unrelated TOML."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path


MANAGED = {
    "enabled": "true",
    "max_concurrent_threads_per_session": "6",
    "default_subagent_model": '"gpt-5.6-terra"',
    "default_subagent_reasoning_effort": '"medium"',
    "interrupt_message": "true",
}

SECTION_RE = re.compile(r"^\s*\[\[?([^\[\]]+)\]\]?\s*(?:#.*)?$")


def validate_toml(text: str, label: str) -> None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{label} is not valid TOML: {exc}") from exc


def managed_lines(missing: set[str] | None = None) -> list[str]:
    selected = MANAGED if missing is None else {k: v for k, v in MANAGED.items() if k in missing}
    return [f"{key} = {value}\n" for key, value in selected.items()]


def merge_text(text: str) -> str:
    if text:
        validate_toml(text, "existing config")

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    in_agents = False
    found_agents = False
    seen: set[str] = set()

    def finish_agents() -> None:
        missing = set(MANAGED) - seen
        output.extend(managed_lines(missing))

    for line in lines:
        section_match = SECTION_RE.match(line.rstrip("\r\n"))
        if section_match:
            if in_agents:
                finish_agents()
                in_agents = False
            section_name = section_match.group(1).strip()
            if section_name == "agents":
                if found_agents:
                    raise ValueError("existing config contains more than one [agents] section")
                found_agents = True
                in_agents = True
                seen = set()
            output.append(line)
            continue

        if in_agents:
            replaced = False
            for key, value in MANAGED.items():
                if re.match(rf"^\s*{re.escape(key)}\s*=", line):
                    if key in seen:
                        raise ValueError(f"existing [agents] section contains duplicate key: {key}")
                    output.append(f"{key} = {value}\n")
                    seen.add(key)
                    replaced = True
                    break
            if replaced:
                continue

        output.append(line)

    if in_agents:
        finish_agents()

    if not found_agents:
        if output and not output[-1].endswith(("\n", "\r")):
            output[-1] += "\n"
        if output and output[-1].strip():
            output.append("\n")
        output.append("[agents]\n")
        output.extend(managed_lines())

    merged = "".join(output)
    validate_toml(merged, "merged config")
    return merged


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, existing_mode)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
    try:
        merged = merge_text(current)
    except ValueError as exc:
        print(f"config merge failed: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if current == merged:
            return 0
        print(f"managed [agents] keys are missing or stale in {args.path}", file=sys.stderr)
        return 1

    if current != merged:
        atomic_write(args.path, merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
